from google import genai
from dotenv import load_dotenv
import os
load_dotenv()
client = genai.Client(api_key="")


def start_chat() :
    # 채팅 세션 시작
    chat = client.chats.create(model="gemini-2.5-flash")

    print("Gemini 챗봇 (종료하려면 'exit' 입력)")

    while True :
        user_input = input("나: ")
        if user_input.lower() in ['exit', 'quit', '종료'] :
            break

        print("Gemini: ", end="", flush=True)

        # 스트리밍 응답 요청
        response = chat.send_message_stream(user_input)

        for chunk in response :
            # 각 조각(chunk)이 도착할 때마다 출력
            print(chunk.text, end="", flush=True)
        print("\n" + "-" * 30)


if __name__ == "__main__" :
    start_chat()
