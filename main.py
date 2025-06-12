import asyncio
import websockets
import json
import time
import sys
import tomllib
import os
import adb_code
from loguru import logger
from typing import Any, List, Optional
from dataclasses import dataclass
from enum import Enum
from pydantic import BaseModel, Field

URL = "ws://127.0.0.1:8080"
TOKEN = ""
ENABLE_GROUP_LIST: List[int] = []

class ADBBot:
    def __init__(self):
        self.seq: int = 1
        self.ws: websockets.ClientConnection
        self.config: ADBBot.Config

        # 配置 logger
        logger.configure(
            handlers=[
                {"sink": sys.stdout, "level": "INFO"},
                {"sink": f"logs/adbbot_{time.strftime('%Y-%m-%d_%H-%M-%S')}.log", "level": "DEBUG", "retention": 3}
            ]
        )

        # 初始化配置
        self.initial_config()

    async def start(self):
        # 连接 Seluded
        await self.connect()

        # 启动事件循环
        await self.event_loop()

    class Config(BaseModel):
        url: str
        token: str
        enable_group_list: list[int]

    def initial_config(self):
        # 从config.toml读取配置, 如果config.toml不存在则使用常量作为默认配置
        if os.path.exists("config.toml"):
            logger.info("读取配置文件: config.toml")
            
            with open("config.toml", "r") as f:
                config_data = f.read()
            
            try:
                self.config = ADBBot.Config.model_validate(tomllib.loads(config_data))
            except tomllib.TOMLDecodeError:
                logger.error("config.toml格式错误, 请检查配置文件!")
                input("按回车键退出...")
                sys.exit(1)
            
            logger.info("配置文件读取成功!")
        else:
            logger.warning("config.toml不存在, 使用默认配置")
            # 生成一个默认配置
            self.config = ADBBot.Config(
                url=URL,
                token=TOKEN,
                enable_group_list=ENABLE_GROUP_LIST
            )
        
        # 打印配置
        logger.info(f"当前配置: {self.config.model_dump_json(indent=4)}")

    async def connect(self):
        logger.info("连接到 Secluded......")

        try:
            self.ws = await websockets.connect(self.config.url)
        except ConnectionRefusedError:
            logger.error("连接失败, 请检查参数是否填写正确!")
            input("按回车键退出...")
            sys.exit(1)
        logger.info("连接成功!")

        # 发送上线包
        logger.info("发送上线包...")
        try:
            await self.call_api({
                "cmd": "SyncOicq",
                "rsp": True,
                "data": {
                    "pid": "adbbot",
                    "name": "ADB 算码机器人",
                    "token": self.config.token,
                }
            })
        except websockets.ConnectionClosed:
            logger.error("连接已关闭, 请检查网络连接!")
            input("按回车键退出...")
            sys.exit(1)
        logger.info("上线包发送成功!")

        # 接收返回消息并判定是否上线成功
        try:
            logger.info("等待上线结果...")
            recv = await self.recv()
            recv_dict = json.loads(recv)
        except websockets.ConnectionClosed:
            logger.error("连接已关闭, 请检查网络连接!")
            input("按回车键退出...")
            sys.exit(1)
        except json.JSONDecodeError:
            logger.error("无法解码 JSON 消息! 上线失败!")
            logger.debug(f"接收到的消息: {recv}")
            input("按回车键退出...")
            sys.exit(1)
        if recv_dict["cmd"] == "Response" and recv_dict["data"]["status"]:
            logger.info("上线成功!")
    
    async def event_loop(self):
        logger.info("开始事件循环...")
        while True:
            try:
                recv = await self.recv()
                recv_dict = json.loads(recv)
                logger.debug(f"接收消息: {recv_dict}")
                # 处理接收到的消息
                await self.handle_message(recv_dict)
            except websockets.ConnectionClosed:
                logger.error("连接已关闭, 请检查网络连接!")
                input("按回车键退出...")
                sys.exit(1)
            except json.JSONDecodeError:
                logger.warning("无法解码 JSON 消息!")
                logger.warning(f"接收到的消息: {recv}")

    class SegmentType(Enum):
        TEXT = "text"
        IMAGE = "image"
        AT = "at"
        FACE = "face"
        REPLY = "reply"
        RECORD = "record"
        VIDEO = "video"
        FILE = "file"
        LOCATION = "location"
        POKE = "poke"

    @dataclass
    class MessageSegment:
        type: "ADBBot.SegmentType"
        data: dict[str, Any]

    @dataclass
    class GroupMessage:
        account: int
        group_id: int
        group_name: str
        msg_id: int
        user_id: int
        user_name: str
        message: list["ADBBot.MessageSegment"]
        
        def __str__(self) -> str:
            message_str: str = ""
            for i in self.message:
                if i.type == ADBBot.SegmentType.TEXT:
                    message_str += i.data["text"]
                elif i.type == ADBBot.SegmentType.AT:
                    message_str += f"@{i.data['name']} "
                # TODO: 处理其他消息类型

                if not message_str == "":
                    message_str += " "
            
            return message_str
        
        def to_plaintext(self) -> str:
            return self.__str__()

    async def handle_message(self, origin_message: dict):
        if origin_message["cmd"] == "PushOicqMsg": # 消息
            data: list[dict] = origin_message["data"]
            
            if "Heartbeat" in data[0].keys() or "System" in data[0].keys():
                # 我服了消息类型什么区分都没有, 就靠一个 "Heartbeat" 来区分心跳包, 真神经
                logger.info("收到心跳包")
                return

            # 初始化信息变量
            account: int = 0
            is_group: bool = False
            msg_id: int = 0
            group_id: int = 0
            group_name: str = ""
            user_id: int = 0
            user_name: str = ""
            message: list[ADBBot.MessageSegment] = []

            # 解析消息内容
            for i,x in enumerate(data):
                if i == 0: # data 的第一项包含账户信息等信息
                    account = x["Account"]
                    is_group = "Group" in x.keys()
                    msg_id = x["MsgId"]
                    user_id = x["Uin"]
                    user_name = x["UinName"]
                    if is_group:
                        group_id = x["GroupId"]
                        group_name = x["GroupName"]
                    
                    if account == user_id: # 收到自己的消息
                        return
                else: # 其他项为消息内容
                    match list(x.keys())[0]:
                        case "Text":
                            message.append(ADBBot.MessageSegment(
                                type=ADBBot.SegmentType.TEXT,
                                data={"text": x["Text"]}
                            ))
                        case "AtUin":
                            message.append(ADBBot.MessageSegment(
                                type=ADBBot.SegmentType.AT,
                                data={"id": x["AtUin"], "name": x["AtName"]}
                            ))
                        # TODO: 添加其他消息类型的处理
            
            # 构建消息
            if is_group:
                msg = ADBBot.GroupMessage(
                    account=int(account),
                    group_id=int(group_id),
                    group_name=group_name,
                    msg_id=int(msg_id),
                    user_id=int(user_id),
                    user_name=user_name,
                    message=message
                )
                logger.info(f"收到群消息: {msg.group_name}({msg.group_id}) - {msg.user_name}({msg.user_id})")
                await self.on_group_message(msg)
            else:
                # TODO: 处理私聊消息
                logger.info(f"收到私聊消息: {user_name}({user_id})")
        else:
            logger.warning(f"未知消息类型: {origin_message['cmd']}")
    
    async def on_group_message(self, message: "ADBBot.GroupMessage"):
        # 检测是否在本群开启
        group_id = message.group_id
        if not group_id in self.config.enable_group_list:
            logger.info(f"群 {group_id} 未开启, 忽略消息")
            return

        message_str = message.to_plaintext()
        if message_str[:4] == "/adb" or message_str[:3] == "adb" or message_str[:4] == "adb/":
            logger.info(f"收到命令: {message_str}")
            if message_str[:3] == "adb":
                origin_code = message_str[3:].strip()
            else:
                origin_code = message_str[4:].strip()
            
            if not origin_code.isdigit():
                logger.warning(f"无效的代码: {origin_code}")
                return
        
            try:
                code_result = adb_code.auto_adb(int(origin_code))
            except adb_code.CodeError as e:
                # 发送计算失败
                logger.warning(f"计算失败: {e}")
                send_message_segments = [
                    ADBBot.MessageSegment(
                        type=ADBBot.SegmentType.AT,
                        data={"id": message.user_id, "name": message.user_name}
                    ),
                    ADBBot.MessageSegment(
                        type=ADBBot.SegmentType.TEXT,
                        data={"text": f"计算失败!"}
                    )
                ]

                send_message = ADBBot.GroupMessage(
                    account=message.account,
                    group_id=message.group_id,
                    group_name=message.group_name,
                    msg_id=message.msg_id,
                    user_id=message.user_id,
                    user_name=message.user_name,
                    message=send_message_segments
                )

                await self.send(send_message)

                return

            logger.info(f"计算结果: {code_result}")

            send_message_segments = [
                # ADBBot.MessageSegment(
                #     type=ADBBot.SegmentType.AT,
                #     data={"id": message.user_id, "name": message.user_name}
                # ),
                ADBBot.MessageSegment(
                    type=ADBBot.SegmentType.TEXT,
                    data={"text": f"结果: {code_result}"}
                )
            ]

            send_message = ADBBot.GroupMessage(
                account=message.account,
                group_id=message.group_id,
                group_name=message.group_name,
                msg_id=message.msg_id,
                user_id=message.user_id,
                user_name=message.user_name,
                message=send_message_segments
            )

            await self.send(send_message)
        elif message_str[:3] == "/zj" or message_str[:2] == "zj" or message_str[:3] == "zj/":
            logger.info(f"收到指令: {message_str}")
            if message_str[:2] == "zj":
                origin_code = message_str[2:].strip()
            else:
                origin_code = message_str[3:].strip()
            
            if not origin_code.isdigit():
                logger.warning(f"无效的代码: {origin_code}")
                return
            
            try:
                code_result = adb_code.auto_zj(int(origin_code))
            except adb_code.CodeError as e:
                # 发送计算失败
                logger.warning(f"计算失败: {e}")
                send_message_segments = [
                    ADBBot.MessageSegment(
                        type=ADBBot.SegmentType.AT,
                        data={"id": message.user_id, "name": message.user_name}
                    ),
                    ADBBot.MessageSegment(
                        type=ADBBot.SegmentType.TEXT,
                        data={"text": f"计算失败!"}
                    )
                ]

                send_message = ADBBot.GroupMessage(
                    account=message.account,
                    group_id=message.group_id,
                    group_name=message.group_name,
                    msg_id=message.msg_id,
                    user_id=message.user_id,
                    user_name=message.user_name,
                    message=send_message_segments
                )

                await self.send(send_message)

                return

            logger.info(f"计算结果: {code_result}")

            send_message_segments = [
                # ADBBot.MessageSegment(
                #     type=ADBBot.SegmentType.AT,
                #     data={"id": message.user_id, "name": message.user_name}
                # ),
                ADBBot.MessageSegment(
                    type=ADBBot.SegmentType.TEXT,
                    data={"text": f"结果: {code_result}"}
                )
            ]

            send_message = ADBBot.GroupMessage(
                account=message.account,
                group_id=message.group_id,
                group_name=message.group_name,
                msg_id=message.msg_id,
                user_id=message.user_id,
                user_name=message.user_name,
                message=send_message_segments
            )

            await self.send(send_message)

    async def recv(self):
        recv = await self.ws.recv()
        logger.debug(f"接收数据: {recv}")
        return recv

    async def send(self, message: GroupMessage):
        """将 GroupMessage 转换为协议要求的字典格式并发送"""
        # TODO: 添加私信发送
        data = [
            {
                "Account": str(message.account),
                "Group": "Group",
                "GroupId": str(message.group_id)
            }
        ]
        # 转换消息内容
        for seg in message.message:
            if seg.type == ADBBot.SegmentType.TEXT:
                data.append({"Text": seg.data["text"]})
            elif seg.type == ADBBot.SegmentType.AT:
                data.append({"AtUin": seg.data["id"], "AtName": seg.data.get("name", "")})
            # TODO: 添加其他类型转换
            # TODO: 添加回复消息的处理(若要添加回复消息需要在data的第一项中添加)
        await self.call_api({
            "cmd": "SendOicqMsg",
            "rsp": False,
            "data": data
        })

    async def call_api(self, data: dict):
        data["seq"] = self.seq
        data_json = json.dumps(data)
        logger.debug(f"发送数据: {data_json}")
        await self.ws.send(data_json)
        self.seq += 1

@logger.catch
def error(exc_type, exc_value, *args, **kwargs):
    if exc_type == KeyboardInterrupt:
        logger.info("退出程序...")
        sys.exit(0)
    else:
        # 按原样返回
        raise exc_type(exc_value)

sys.excepthook = error

if __name__ == "__main__":
    bot = ADBBot()
    asyncio.run(bot.start())