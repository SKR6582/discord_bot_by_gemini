from discord.ext import commands
from dotenv import load_dotenv
import discord
import os
import asyncio
from google import genai

# -------------------- 기본 설정 --------------------
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_BOT_MPSB")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 메시지 콘텐츠 접근을 위해 Intent 활성화
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(intents=intents)

# 실행 중 Task 저장 (user_id 기준)
running_tasks: dict[int, asyncio.Task] = {}

# -------------------- 채널 히스토리 → 프롬프트 컨텍스트 --------------------
async def build_channel_context(
    ctx: discord.ApplicationContext,
    history_limit: int = 20,
    max_chars: int = 6000,
) -> str:
    """
    최근 채널 메시지를 불러와 AI에게 줄 컨텍스트 문자열로 변환.
    - history_limit: 불러올 최대 메시지 수
    - max_chars: 최종 컨텍스트 최대 글자수 (초과 시 앞쪽부터 잘라냄)
    """
    channel = ctx.channel  # type: ignore[assignment]
    lines: list[str] = []

    # 오래된 것부터 최근순으로 정렬해서 누적
    async for m in channel.history(limit=history_limit, oldest_first=True):  # type: ignore[attr-defined]
        # 내용이 없으면 스킵 (이모지/임베드 전용 등)
        text = (m.content or "").strip()
        if not text:
            continue

        author = m.author
        # 역할 태그: 호출자/봇/타 유저를 구분
        if author.id == ctx.bot.user.id:
            role = "assistant"
        elif author.id == ctx.user.id:
            role = "user"
        else:
            role = "other"

        # 너무 긴 줄은 줄임
        if len(text) > 1000:
            text = text[:1000] + " …"

        name = getattr(author, "display_name", getattr(author, "name", "user"))
        lines.append(f"[{role}] {name}: {text}")

    combined = "\n".join(lines)

    # 최대 길이 초과 시 앞쪽(가장 오래된)부터 잘라서 최근 대화 우선 보존
    if len(combined) > max_chars:
        combined = combined[-max_chars:]

    if not combined:
        return ""

    header = (
        "You are an AI assistant in a Discord channel. Use the recent conversation "
        "below to maintain context. Respond helpfully in the same language as the user.\n\n"
        "[Recent Conversation]\n"
    )
    return header + combined

# -------------------- Gemini 스트리밍 --------------------
async def stream_gemini(ctx: discord.ApplicationContext, content: str):
    client = genai.Client(api_key=GEMINI_API_KEY)
    chat = client.chats.create(model="gemini-2.5-flash")

    full_text = ""
    buffer = ""

    try:
        for chunk in chat.send_message_stream(content):
            if not chunk.text:
                continue

            full_text += chunk.text
            buffer += chunk.text

            if len(buffer) >= 120:
                await ctx.edit(content=full_text)
                buffer = ""

        await ctx.edit(content=full_text, view=None)

    except asyncio.CancelledError:
        await ctx.edit(content=full_text + "\n\n⛔ 중단됨", view=None)
        raise

    finally:
        running_tasks.pop(ctx.user.id, None)

# -------------------- Stop 버튼 --------------------
class StopView(discord.ui.View):
    def __init__(self, owner_id: int, task: asyncio.Task):
        super().__init__(timeout=None)
        self.owner_id = owner_id
        self.task = task

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)
    async def stop(
        self,
        button: discord.ui.Button,
        interaction: discord.Interaction
    ):
        if interaction.user.id != self.owner_id:
            await interaction.response.defer()
            return

        if not self.task.done():
            self.task.cancel()

        await interaction.response.defer()

# -------------------- Slash Command --------------------
@bot.slash_command(name="run", description="Gemini 스트리밍 실행 (채널 히스토리로 문맥 유지)")
async def run(
    ctx: discord.ApplicationContext,
    content: str,
    use_history: bool = True,
    history_limit: int = 20,
):
    """use_history=True면 같은 채널 최근 대화를 컨텍스트로 활용합니다."""
    # 이미 실행 중이면 차단
    if ctx.user.id in running_tasks:
        await ctx.respond("이미 실행 중인 작업이 있어.")
        return

    await ctx.respond("Running...")

    # 프롬프트 구성
    prompt = content
    if use_history:
        try:
            context_str = await build_channel_context(ctx, history_limit=history_limit)
        except Exception:
            context_str = ""  # 히스토리 조회 실패 시 조용히 무시하고 단일 프롬프트만 사용
        if context_str:
            prompt = f"{context_str}\n\n[User Request]\n{content}"

    task = asyncio.create_task(stream_gemini(ctx, prompt))
    running_tasks[ctx.user.id] = task

    view = StopView(ctx.user.id, task)
    await ctx.edit(view=view)

# -------------------- Ready --------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.change_presence(activity=discord.Game("/run"))

# -------------------- Run --------------------
bot.run(DISCORD_TOKEN)