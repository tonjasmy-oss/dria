#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import time
import os
import hmac
import hashlib
import base64
import urllib.parse
import datetime
import socket
import subprocess
from typing import Dict, Tuple, List, Optional, Any

# ======== 可配置项 ========
# 建议用环境变量传入，或直接填常量
DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK",
                             "https://oapi.dingtalk.com/robot/send?access_token=d0c5d70533c293c1b9d764ffe9057e4c9c0ca88775508d8ada6d18c2a320a7fd")
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "SECe6c9b7d8015db8058a7fe90f8d7f31067aa9a131e9e90208e6d0994ba6d89827")
SERVER_NAME = "dria积分播报"
DRIA_API_KEY = os.getenv("DRIA_API_KEY", "YOUR_DK_API_KEY")

# 文件路径
WALLET_FILE = "s-wallets.txt"
PREVIOUS_FILE = "previous_scores.txt"
SUMMARY_FILE = "S-Summary.txt"
HISTORY_FILE = "S-history.json"

INITIAL_INTERVAL = 300  # 5 分钟
IS_FIRST_LOOP = True


# ======== 工具函数 ========
def run_command(command: str, check: bool = True) -> Optional[str]:
    try:
        result = subprocess.run(command, shell=True, check=check, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"⚠️ 命令执行失败: {command}\n错误: {e.stderr}")
        return None


def normalize_address(address: str) -> str:
    a = address.strip().lower()
    return a if a.startswith("0x") else "0x" + a


def mask_wallet_address(address: str) -> str:
    return f"****{address[-6:]}" if len(address) > 6 else address


def generate_sign(secret: str) -> Tuple[str, str]:
    timestamp = str(round(time.time() * 1000))
    secret_enc = secret.encode("utf-8")
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    hmac_code = hmac.new(secret_enc, string_to_sign, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote(base64.b64encode(hmac_code))
    return timestamp, sign


def send_to_dingtalk(message: str):
    max_len = 2000
    parts = [message[i:i + max_len] for i in range(0, len(message), max_len)] or [message]
    timestamp, sign = generate_sign(DINGTALK_SECRET)
    url = f"{DINGTALK_WEBHOOK}&timestamp={timestamp}&sign={sign}"
    headers = {"Content-Type": "application/json"}
    for part in parts:
        body = {"msgtype": "text", "text": {"content": f"【{SERVER_NAME}】\n{part}"}}
        try:
            r = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
            if r.status_code == 200:
                print("✅ 钉钉发送成功")
            else:
                print(f"⚠️ 钉钉发送失败: {r.status_code}, {r.text}")
        except requests.RequestException as e:
            print(f"⚠️ 钉钉发送异常: {e}")
        time.sleep(2)


def choose_mode() -> Tuple[str, str]:
    print("是否发送钉钉通知？")
    send_dingtalk = input("输入 y 发送钉钉，输入 n 仅终端输出 (y/n): ").strip().lower()
    while send_dingtalk not in {"y", "n"}:
        send_dingtalk = input("输入错误，请输入 y 或 n: ").strip().lower()

    if send_dingtalk == "n":
        return "no", ""

    print("请选择钉钉发送模式：\n1. 只发详细\n2. 详细+摘要\n3. 只发摘要")
    mode = input("输入模式编号 (1/2/3): ").strip()
    while mode not in {"1", "2", "3"}:
        mode = input("输入错误，请输入 1 / 2 / 3: ").strip()

    return "yes", mode


def choose_interval_minutes() -> int:
    val = input("请输入循环间隔（分钟，>=1，建议120）: ").strip()
    try:
        minutes = max(1, int(val))
    except:
        minutes = 120
    return minutes


def choose_execution_mode() -> str:
    print("请选择执行模式：")
    print("1. 单次执行")
    print("2. 循环执行")
    mode = input("请输入选项 (1/2): ").strip()
    while mode not in {"1", "2"}:
        mode = input("输入错误，请输入 1 或 2: ").strip()

    return "once" if mode == "1" else "loop"


def load_wallet_addresses(path: str) -> Dict[str, str]:
    res = {}
    server_prefix = SERVER_NAME.split("dria")[0].strip() if "dria" in SERVER_NAME else SERVER_NAME
    try:
        with open(path, "r", encoding="utf-8") as f:
            auto_index = 1
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if "," in s:
                    parts = s.split(",", 1)
                    if len(parts) >= 2:
                        server, addr = parts[0], parts[1]
                        res[server.strip()] = addr.strip()
                else:
                    res[f"{server_prefix}_{auto_index}"] = s
                    auto_index += 1
    except FileNotFoundError:
        print(f"⚠️ 未找到钱包文件 {path}")
    return res


def load_previous_scores(path: str) -> Dict[str, float]:
    prev = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 3:
                    address = parts[1].strip()
                    try:
                        score = float(parts[2].strip())
                        prev[normalize_address(address)] = score
                    except ValueError:
                        print(f"⚠️ 无法解析积分值: {line.strip()}")
    except FileNotFoundError:
        print("ℹ️ 首次运行：未发现 previous_scores.txt，默认上次积分为 0。")
    except Exception as e:
        print(f"⚠️ 读取 {path} 出错: {e}")
    return prev


def save_current_scores(path: str, wallet_dict: Dict[str, str], curr: Dict[str, float]):
    with open(path, "w", encoding="utf-8") as f:
        for server, address in wallet_dict.items():
            addr = normalize_address(address)
            f.write(f"{server},{addr},{curr.get(addr, 0.0)}\n")
    print(f"✅ 当前积分信息已保存到 {path}")


def get_server_info() -> Tuple[str, str]:
    server_name = socket.gethostname()
    if not server_name:
        print("⚠️ 无法获取主机名")
        server_name = "unknown"

    server_ip = None
    ip_output = run_command(
        "ip -4 addr show | grep inet | grep -v 127.0.0.1 | awk '{print $2}' | cut -d'/' -f1 | head -n 1")
    if ip_output:
        server_ip = ip_output
    else:
        print("⚠️ 无法获取内网IP，尝试获取公网IP...")
        try:
            server_ip = requests.get("https://ifconfig.me", timeout=5).text.strip()
        except requests.RequestException:
            print("⚠️ 无法获取公网IP")
            server_ip = "unknown"

    return server_name, server_ip


def get_dria_signature() -> Dict[str, str]:
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    timestamp = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    signature = hmac.new(
        DRIA_API_KEY.encode("utf-8"),
        timestamp.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return {
        "x-message": timestamp,
        "x-signature": signature,
        "x-api-key": DRIA_API_KEY
    }


def get_score_and_percentile(address: str, max_retries: int = 3) -> Tuple[float, str]:
    url = f"https://mainnet.dkn.dria.co/dashboard/v1/node/points/all-time/{address}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://dria.co/",
        **get_dria_signature()
    }
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code}")
            data = r.json()
            if "points" in data:
                score = float(data["points"])
            elif "score" in data:
                score = float(data["score"])
            else:
                raise ValueError("返回缺少积分字段")
            percentile = data.get("percentile", "未知排名")
            if isinstance(percentile, str) and percentile.startswith("top_"):
                percentile = f"前{percentile[4:]}%"
            elif isinstance(percentile, (float, int)):
                percentile = f"前{percentile}%"
            return score, percentile
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                print(f"⚠️ 获取失败 {address}: {e}")
                return 0.0, "未知排名"


def load_last_history_record() -> Optional[Dict[str, Any]]:
    if not os.path.exists(HISTORY_FILE):
        return None
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            obj = json.load(f)
            if isinstance(obj, dict) and "records" in obj and obj["records"]:
                return obj["records"][-1]
    except:
        pass
    return None


def append_history_record(timestamp_str: str, total_score: float, success_count: int, increment: float):
    data = {"records": []}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "records" not in data:
                data = {"records": []}
        except:
            data = {"records": []}
    data["records"].append({
        "timestamp": timestamp_str,
        "total_score": total_score,
        "success_count": success_count,
        "increment": increment
    })
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ 历史已写入 {HISTORY_FILE}")


def build_summary_block(now_str: str,
                        success_count: int,
                        fail_count: int,
                        no_growth_count: int,
                        growth_count: int,
                        total_score: float,
                        avg_score: float,
                        max_score: float,
                        min_score: float,
                        total_increment: float,
                        hourly_growth: float,
                        hourly_growth_per_addr: float) -> str:
    server_name, server_ip = get_server_info()
    return (
        f"🏆 查询时间: {now_str}\n"
        f"🖥️ 服务器主机名: {server_name}\n"
        f"🌐 服务器IP: {server_ip}\n"
        f"📊 统计: 成功 {success_count} 个, 失败 {fail_count} 个 \n"
        f"⏱️ 积分未增长: {no_growth_count}个，积分增长: {growth_count}个\n"
        f"💰 积分总和: {total_score:.2f}\n"
        f"📈 平均积分: {avg_score:.2f}\n"
        f"🏆 最高积分: {max_score:.2f}\n"
        f"📉 最低积分: {min_score:.2f}\n"
        f"📊 总积分增量: {total_increment:+.2f}\n"
        f"⏱️ 平均每小时积分增长量: {hourly_growth:.2f}\n"
        f"⏱️ 平均每小时每个积分增长量: {hourly_growth_per_addr:.4f}\n"
        f"================================================="
    )


if __name__ == "__main__":
    send_option, mode = choose_mode()

    # 选择执行模式
    execution_mode = choose_execution_mode()

    # 如果是循环执行模式，则选择间隔时间
    if execution_mode == "loop":
        interval_minutes = choose_interval_minutes()
    else:
        interval_minutes = 0  # 单次执行不需要间隔时间

    if send_option == "yes":
        message = f"📣 已选择模式: {mode} | "
        if execution_mode == "loop":
            message += f"循环执行 | 循环间隔: {interval_minutes} 分钟"
        else:
            message += "单次执行"
        print(message)
        send_to_dingtalk("脚本已启动！开始监控积分变化...")
    else:
        message = "📣 钉钉通知已禁用 | "
        if execution_mode == "loop":
            message += f"循环执行 | 循环间隔: {interval_minutes} 分钟"
        else:
            message += "单次执行"
        print(message)

    first_loop = IS_FIRST_LOOP
    while True:
        ts_file = time.strftime("%Y%m%d_%H%M%S")
        ts_human = time.strftime("%Y-%m-%d %H:%M:%S")

        wallet_dict = load_wallet_addresses(WALLET_FILE)
        if not wallet_dict:
            print("⚠️ 钱包地址列表为空，等待下轮。")
            if execution_mode == "once":
                break
            time.sleep(10)
            continue

        prev_scores = load_previous_scores(PREVIOUS_FILE)
        curr_scores: Dict[str, float] = {}

        success_count = 0
        fail_count = 0
        growth_count = 0
        no_growth_count = 0
        total_increment = 0.0

        # 统计满足条件的地址数量
        over_10000_count = 0  # 超过10000分的地址数
        top_50_percent_count = 0  # 排名前50%的地址数
        over_10000_and_top_50_percent_count = 0  # 同时满足两个条件的地址数

        detail_lines: List[str] = [f"⏰ 查询时间: {ts_human}"]
        result_lines: List[str] = [f"⏰ 查询时间: {ts_human}"]

        print("\n" + "=" * 60)
        print(f"{'服务器':<10} | {'钱包地址':<42} | {'积分':<10} | {'排名':<10} | {'增量':<10}")
        print("-" * 60)

        for server, addr in wallet_dict.items():
            addr_norm = normalize_address(addr)
            score, percentile = get_score_and_percentile(addr_norm)
            curr_scores[addr_norm] = score

            if score >= 0:
                success_count += 1
            else:
                fail_count += 1

            prev = prev_scores.get(addr_norm, 0.0)
            inc = score - prev
            total_increment += inc
            if inc > 0:
                growth_count += 1
            else:
                no_growth_count += 1

            # 统计满足条件的地址数量
            is_over_10000 = score > 10000
            is_top_50_percent = False
            if percentile != "未知排名":
                if isinstance(percentile, str) and percentile.startswith("前"):
                    try:
                        percent_value = float(percentile[1:].rstrip('%'))
                        is_top_50_percent = percent_value <= 50
                    except:
                        pass

            if is_over_10000:
                over_10000_count += 1

            if is_top_50_percent:
                top_50_percent_count += 1

            if is_over_10000 and is_top_50_percent:
                over_10000_and_top_50_percent_count += 1

            detail_lines.append(
                f"{server} | 钱包: {mask_wallet_address(addr_norm)} | 积分: {score} | 排名: {percentile} | 增量: {inc:.2f}"
            )
            result_lines.append(
                f"{server} | 钱包: {addr_norm} | 积分: {score} | 排名: {percentile} | 增量: {inc:.2f}"
            )

            print(f"{server:<10} | {addr_norm:<42} | {score:<10.2f} | {percentile:<10} | {inc:+.2f}")

        n = max(1, len(wallet_dict))
        total_score = sum(curr_scores.values())
        avg_score = total_score / n
        max_score = max(curr_scores.values()) if curr_scores else 0.0
        min_score = min(curr_scores.values()) if curr_scores else 0.0

        last_record = load_last_history_record()
        if last_record:
            try:
                t_last = datetime.datetime.strptime(last_record["timestamp"], "%Y-%m-%d %H:%M:%S")
                t_now = datetime.datetime.strptime(ts_human, "%Y-%m-%d %H:%M:%S")
                delta_hours = max(1e-6, abs((t_now - t_last).total_seconds()) / 3600.0)
            except:
                delta_hours = max(1e-6, interval_minutes / 60.0)
        else:
            delta_hours = max(1e-6, interval_minutes / 60.0)

        hourly_growth = total_increment / delta_hours
        hourly_growth_per_addr = hourly_growth / n

        summary_block = build_summary_block(
            now_str=ts_human,
            success_count=success_count,
            fail_count=fail_count,
            no_growth_count=no_growth_count,
            growth_count=growth_count,
            total_score=total_score,
            avg_score=avg_score,
            max_score=max_score,
            min_score=min_score,
            total_increment=total_increment,
            hourly_growth=hourly_growth,
            hourly_growth_per_addr=hourly_growth_per_addr
        )

        # 在摘要中添加新的统计信息
        extended_summary = (
            f"{summary_block}\n"
            f"📈 超过10000分地址数: {over_10000_count}\n"
            f"🏆 排名前50%地址数: {top_50_percent_count}\n"
            f"⭐ 超10000分且排名前50%地址数: {over_10000_and_top_50_percent_count}"
        )

        save_current_scores(PREVIOUS_FILE, wallet_dict, curr_scores)

        result_filename = f"S_scores_{ts_file}.txt"
        with open(result_filename, "w", encoding="utf-8") as rf:
            rf.write("\n".join(result_lines) + "\n\n" + extended_summary + "\n")
        print(f"✅ 查询完成！结果已保存至 {result_filename}")

        with open(SUMMARY_FILE, "a", encoding="utf-8") as sf:
            sf.write(extended_summary + "\n")
        print(f"✅ 摘要已追加至 {SUMMARY_FILE}")

        append_history_record(
            timestamp_str=ts_human,
            total_score=total_score,
            success_count=success_count,
            increment=total_increment
        )

        print("=" * 60)
        print(extended_summary)
        print("=" * 60 + "\n")

        has_change = abs(total_increment) > 0.001
        if send_option == "yes" and (has_change or first_loop):
            if mode == "1":
                send_to_dingtalk("\n".join(detail_lines))
            elif mode == "2":
                send_to_dingtalk("\n".join(detail_lines))
                send_to_dingtalk(
                    extended_summary + f"\n✅ 查询完成！结果已保存至 {result_filename}\n✅ 摘要信息已保存至 {SUMMARY_FILE}\n✅ 历史记录已保存至 {HISTORY_FILE}"
                )
            elif mode == "3":
                send_to_dingtalk(
                    extended_summary + f"\n✅ 查询完成！结果已保存至 {result_filename}\n✅ 摘要信息已保存至 {SUMMARY_FILE}\n✅ 历史记录已保存至 {HISTORY_FILE}"
                )
        elif send_option == "no":
            print("📌 钉钉通知已禁用，结果仅在终端显示")
        else:
            print("📌 积分无变化，本轮不推送钉钉")

        # 如果是单次执行模式，则退出循环
        if execution_mode == "once":
            print("✅ 单次执行完成，程序退出。")
            break

        wait_seconds = INITIAL_INTERVAL if first_loop else max(60, interval_minutes * 60)
        first_loop = False
        for remaining in range(wait_seconds, 0, -1):
            hrs, rem = divmod(remaining, 3600)
            mins, secs = divmod(rem, 60)
            print(f"\r⏳ 剩余时间: {hrs:02d}:{mins:02d}:{secs:02d}", end="", flush=True)
            time.sleep(1)
        print("\n⏰ 开始新一轮查询！")