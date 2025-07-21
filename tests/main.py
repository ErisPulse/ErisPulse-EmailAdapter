# ErisPulse 主程序文件
import asyncio
import os
from ErisPulse import sdk

async def send_example_email():
    try:
        html_content = """
        <h1>HTML内容测试</h1>
        <p>这是一封包含<strong>HTML格式</strong>的邮件</p>
        <p>颜色: <span style="color:red;">红色文字</span></p>
        """
        
        result = await sdk.adapter.email.Send \
            .To("suyu@anran.xyz") \
            .Subject("HTML邮件测试") \
            .Cc(["wsu2059@qq.com"]) \
            .Html(html_content)
            
        sdk.logger.info(f"HTML邮件发送结果: {result}")
        
    except Exception as e:
        sdk.logger.error(f"发送邮件失败: {str(e)}")

async def handle_incoming_emails(event):
    try:
        if event.get("platform") != "email":
            return
        sdk.logger.info(f"收到新邮件: {event}")

        sdk.logger.info(f"\n收到新邮件:")
        sdk.logger.info(f"发件人: {event['email_raw']['from']}")
        sdk.logger.info(f"主题: {event['email_raw']['subject']}")
        sdk.logger.info(f"时间: {event['email_raw']['date']}")
        
        if event['email_raw']['text_content']:
            sdk.logger.info("\n文本内容:")
            sdk.logger.info(event['email_raw']['text_content'])
        
        for attachment in event.get('attachments', []):
            filename = f"downloads/{attachment['filename']}"
            os.makedirs("downloads", exist_ok=True)
            with open(filename, "wb") as f:
                f.write(attachment['data'])
            sdk.logger.info(f"附件已保存: {filename}")
        
        yunhu = sdk.adapter.get("Yunhu")

        content = f"""
        <h1>收到新邮件</h1>
        <p>发件人: {event['email_raw']['from']}</p>
        <p>主题: {event['email_raw']['subject']}</p>
        <p>时间: {event['email_raw']['date']}</p>
        {event['email_raw']['html_content']}
        {"<p>附件: <ul>" + "".join([f"<li>{att['filename']}</li>" for att in event['attachments']]) + "</ul></p>" if event.get('attachments') else ""}
        """
        
        await yunhu.Send.To("group", "635409929").Html(content)

        if event['attachments']:
            if event['attachments'][0]['filename'].split(".")[-1].lower() in ["jpg", "png", "gif", "bmp", "jpeg"]:
                await yunhu.Send.To("group", "635409929").Image(event['attachments'][0]['data'])
            else:
                await yunhu.Send.To("group", "635409929").File(event['attachments'][0]['data'], filename=event['attachments'][0]['filename'])
            
    except Exception as e:
        sdk.logger.error(f"处理邮件时出错: {str(e)}")

async def main():
    try:
        if not sdk.init():
            sdk.logger.error("SDK初始化失败")
            return
        
        await sdk.adapter.startup()

        sdk.adapter.on("message")(handle_incoming_emails)
        
        await send_example_email()
        
        sdk.logger.info("程序已启动，等待接收邮件...")
        sdk.logger.info("按 Ctrl+C 停止程序")
        
        # 保持程序运行
        await asyncio.Event().wait()
        
    except Exception as e:
        sdk.logger.error(f"程序运行出错: {str(e)}")
    except KeyboardInterrupt:
        sdk.logger.info("正在停止程序...")
    finally:
        await sdk.adapter.shutdown()
        sdk.logger.info("程序已停止")

if __name__ == "__main__":
    asyncio.run(main())