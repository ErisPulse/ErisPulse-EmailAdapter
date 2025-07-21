import asyncio
from ErisPulse import sdk

async def main():
    # 初始化 ErisPulse SDK
    if not sdk.init():
        print("ErisPulse 初始化失败")
        return
    
    await sdk.adapter.startup()

    await asyncio.sleep(1)

    # 发送邮件并检查结果
    result = await sdk.adapter.email.Send.To("suyu@anran.xyz").Text("Hello World", subject="测试邮件")
    if result["status"] == "ok":
        print(f"\n邮件发送成功! 消息ID: {result['message_id']}\n")
    else:
        print(f"\n邮件发送失败: {result['message']}\n")

    @sdk.adapter.on("message")
    async def handle_message(data):
        if data.get("platform") == "email":
            print("\n" + "="*50)
            print(f"收到新邮件 (ID: {data['id']})")
            print(f"时间: {data['time']}")
            print(f"发件人: {data.get('email_from', '未知')}")
            print(f"收件人: {data.get('email_to', '未知')}")
            print(f"主题: {data.get('email_subject', '无主题')}")
            print("-"*20 + " 内容 " + "-"*20)
            
            # 打印消息内容
            for segment in data.get("message", []):
                if segment["type"] == "text":
                    print(segment["data"]["text"])
            
            print("="*50 + "\n")

    # 打印启动信息
    print("="*50)
    print("ErisPulse 邮箱适配器已启动")
    print("正在监听新邮件...")
    print("按 Ctrl+C 退出")
    print("="*50)

    # 保持程序运行
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        print("\n收到停止信号，正在关闭...")
    finally:
        # 关闭适配器
        await sdk.adapter.shutdown()
        print("邮箱适配器已关闭")

if __name__ == "__main__":
    asyncio.run(main())