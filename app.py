import os
import requests
import streamlit as st
from google import genai
from google.genai import types

from prompts import SYSTEM_PROMPT

st.set_page_config(
    page_title="Snap & Study",
    page_icon="📚",
    layout="wide",
)

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", "")).strip()
TELEGRAM_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()

MODEL_OPTIONS = {
    "gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite (Recommended - Fast & No 503 Errors)",
    "gemini-3.8-flash": "Gemini 3.8 Flash (Frontier - 20 req/day Free Tier Limit)",
    "gemini-3.5-flash": "Gemini 3.5 Flash (Balanced)",
}

for key, default in [
    ("student_name", "Uzair"),
    ("telegram_chat_id", "8473443209"),
    ("messages", []),
    ("explanation", ""),
    ("selected_model", "gemini-3.5-flash-lite"),
    ("active_model", "gemini-3.5-flash-lite"),
    ("chat_session", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


@st.cache_resource
def get_gemini_client(api_key: str):
    return genai.Client(api_key=api_key)


def analyze_study_image(client, image_part, prompt_text, target_model="gemini-3.5-flash-lite"):
    """Analyze image with automatic fallback if target_model returns 503/429."""
    models_to_try = [target_model]
    if target_model != "gemini-3.5-flash-lite":
        models_to_try.append("gemini-3.5-flash-lite")

    last_error = None
    for model_name in models_to_try:
        try:
            chat = client.chats.create(
                model=model_name,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT
                ),
            )
            response = chat.send_message([image_part, prompt_text])
            if not response.text:
                raise RuntimeError("Gemini returned an empty response.")
            return response.text, chat, model_name
        except Exception as error:
            err_msg = str(error)
            is_transient = any(
                c in err_msg
                for c in ["503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"]
            )
            if is_transient and model_name != "gemini-3.5-flash-lite":
                last_error = error
                st.toast(
                    f"⚠️ {model_name} is experiencing high demand (503). Retrying automatically with Gemini 3.5 Flash-Lite...",
                    icon="🔄",
                )
                continue
            raise error

    raise last_error


def ask_followup(client, chat_session, question_text, target_model="gemini-3.5-flash-lite"):
    """Send follow-up question preserving chat session with fallback."""
    if chat_session is None:
        chat_session = client.chats.create(
            model=target_model,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        )

    try:
        response = chat_session.send_message(question_text)
        if not response.text:
            raise RuntimeError("Gemini returned an empty response.")
        return response.text, chat_session, target_model
    except Exception as error:
        err_msg = str(error)
        is_transient = any(
            c in err_msg
            for c in ["503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"]
        )
        if is_transient and target_model != "gemini-3.5-flash-lite":
            try:
                fallback_chat = client.chats.create(
                    model="gemini-3.5-flash-lite",
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT
                    ),
                    history=chat_session.get_history(),
                )
                response = fallback_chat.send_message(question_text)
                st.toast(
                    "⚠️ Switched to Gemini 3.5 Flash-Lite due to server load.",
                    icon="🔄",
                )
                return response.text, fallback_chat, "gemini-3.5-flash-lite"
            except Exception as fb_err:
                raise fb_err
        raise error


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Add TELEGRAM_BOT_TOKEN to secrets.toml")

    chat_id = st.session_state.telegram_chat_id.strip()
    if not chat_id:
        raise RuntimeError("Enter your Telegram chat ID.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    # Truncate to Telegram's 4096 character limit
    safe_text = message[:4000]

    response = requests.post(
        url,
        data={"chat_id": chat_id, "text": safe_text},
        timeout=20,
    )

    data = response.json()
    if not response.ok or not data.get("ok"):
        desc = data.get("description", "Telegram error")
        if "chat not found" in desc:
            desc = (
                "Chat not found. Please open Telegram, search for "
                "@SnapAndStudyLearningBot, and tap START first!"
            )
        raise RuntimeError(desc)


# ---------------------------------------------------------
# Sidebar
# ---------------------------------------------------------
st.sidebar.title("📚 Snap & Study")
st.sidebar.caption("Learn from a photo, one step at a time.")

page = st.sidebar.radio(
    "Navigation",
    ["Home", "Onboarding", "Study Chat", "About"],
)

st.sidebar.divider()
st.sidebar.subheader("⚙️ Model Settings")

current_sel = st.session_state.get("selected_model", "gemini-3.5-flash-lite")
model_keys = list(MODEL_OPTIONS.keys())
current_idx = model_keys.index(current_sel) if current_sel in model_keys else 0

chosen_model = st.sidebar.selectbox(
    "Choose Gemini Model:",
    options=model_keys,
    format_func=lambda k: MODEL_OPTIONS[k],
    index=current_idx,
    help="Gemini 3.5 Flash-Lite avoids 503 high-demand errors and rate limits on free accounts.",
)

if chosen_model != st.session_state.get("selected_model"):
    st.session_state.selected_model = chosen_model
    st.session_state.active_model = chosen_model

st.sidebar.caption(f"Active model: `{st.session_state.get('active_model', chosen_model)}`")

st.sidebar.divider()
st.sidebar.subheader("📡 Bot Status")
st.sidebar.caption("✅ Google AI Studio: Connected")
st.sidebar.caption("✅ Telegram Bot: @SnapAndStudyLearningBot")

if st.sidebar.button("🔔 Test Telegram Ping", use_container_width=True):
    try:
        send_telegram(
            f"👋 Hi {st.session_state.student_name}! Your Snap & Study Telegram connection is working perfectly! 📚"
        )
        st.sidebar.success("Test message sent! Check Telegram 📲")
    except Exception as e:
        st.sidebar.error(f"Failed to send: {e}")

# ---------------------------------------------------------
# Page: Home
# ---------------------------------------------------------
if page == "Home":
    st.title("📚 Snap & Study")
    st.subheader("Turn your study photos into clear explanations.")

    st.write(
        "Upload a question, diagram, or notes. "
        "Gemini explains them in simple language."
    )

    st.info(
        "Start on the Onboarding page, "
        "then open Study Chat."
    )

    if st.session_state.student_name:
        st.success(f"Welcome, {st.session_state.student_name}!")

    st.markdown(
        """
        ### How it works

        1. Complete onboarding (connect your Telegram).
        2. Upload a study image.
        3. Get a clear, step-by-step explanation.
        4. Ask follow-up questions.
        5. Send the summary to your Telegram!
        """
    )


elif page == "Onboarding":
    st.title("👋 Student Onboarding")

    with st.expander("ℹ️ How to connect your Telegram Bot", expanded=True):
        st.markdown(
            """
            1. Open Telegram and search for [@SnapAndStudyLearningBot](https://t.me/SnapAndStudyLearningBot) (or click the link).
            2. Tap **START** in the chat with the bot.
            3. Enter your details below. Your Telegram Chat ID is **`8473443209`**.
            """
        )

    with st.form("onboarding"):
        name = st.text_input(
            "Student name",
            value=st.session_state.student_name,
        )

        chat_id = st.text_input(
            "Telegram chat ID",
            value=st.session_state.telegram_chat_id,
        )

        submit = st.form_submit_button(
            "Save and continue 🚀",
            type="primary",
            use_container_width=True,
        )

    if submit:
        if not name.strip() or not chat_id.strip():
            st.error("Please fill in both your name and Telegram chat ID.")
        else:
            st.session_state.student_name = name.strip()
            st.session_state.telegram_chat_id = chat_id.strip()
            st.success("Details saved successfully!")


elif page == "Study Chat":
    st.title("🧠 Study Chat")

    if not st.session_state.student_name:
        st.warning("Complete Onboarding first.")
    else:
        st.write(f"Hello, **{st.session_state.student_name}**!")

        uploaded = st.file_uploader(
            "Upload a study image (problem, diagram, or notes)",
            type=["png", "jpg", "jpeg"],
        )

        if uploaded:
            st.image(
                uploaded,
                caption="Uploaded study material",
                use_container_width=True,
            )

            if st.button("🔍 Explain this image", type="primary"):
                with st.spinner("Analyzing your study image..."):
                    try:
                        if not GEMINI_API_KEY:
                            raise RuntimeError("Add GEMINI_API_KEY to secrets.toml")

                        client = get_gemini_client(GEMINI_API_KEY)
                        part = types.Part.from_bytes(
                            data=uploaded.getvalue(),
                            mime_type=uploaded.type,
                        )

                        chosen = st.session_state.get("selected_model", "gemini-3.5-flash-lite")
                        answer, chat_obj, used_model = analyze_study_image(
                            client,
                            part,
                            "Explain this study image in simple English, step by step where needed.",
                            target_model=chosen,
                        )

                        st.session_state.explanation = answer
                        st.session_state.chat_session = chat_obj
                        st.session_state.active_model = used_model
                        st.session_state.messages = [
                            {
                                "role": "user",
                                "text": "Explain the uploaded study image.",
                            },
                            {
                                "role": "assistant",
                                "text": answer,
                            },
                        ]
                        st.rerun()

                    except Exception as e:
                        st.error(f"Could not analyze image: {e}")

        if st.session_state.explanation:
            st.markdown("### 📝 Explanation")
            st.markdown(st.session_state.explanation)

            if st.button("📨 Send explanation to Telegram"):
                try:
                    send_telegram(
                        f"📚 Snap & Study Explanation\n"
                        f"Student: {st.session_state.student_name}\n\n"
                        f"{st.session_state.explanation}"
                    )
                    st.success("Explanation sent to Telegram! 📲")
                except Exception as e:
                    st.error(f"Could not send: {e}")

        st.divider()
        st.subheader("💬 Ask a follow-up question")

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["text"])

        question = st.chat_input("Ask a follow-up question about this study material...")

        if question:
            if not st.session_state.explanation:
                st.warning("Please upload and explain an image first.")
            else:
                st.session_state.messages.append({
                    "role": "user",
                    "text": question,
                })

                with st.chat_message("assistant"):
                    with st.spinner("Thinking..."):
                        try:
                            client = get_gemini_client(GEMINI_API_KEY)
                            chosen = st.session_state.get("selected_model", "gemini-3.5-flash-lite")
                            answer, updated_chat, used_model = ask_followup(
                                client,
                                st.session_state.chat_session,
                                question,
                                target_model=chosen,
                            )
                            st.session_state.chat_session = updated_chat
                            st.session_state.active_model = used_model
                            st.markdown(answer)

                            st.session_state.messages.append({
                                "role": "assistant",
                                "text": answer,
                            })

                        except Exception as e:
                            st.error(f"Gemini request failed: {e}")


elif page == "About":
    st.title("ℹ️ About Snap & Study")

    st.write(
        "Snap & Study is an educational assistant "
        "that uses Gemini to explain study images "
        "and Telegram to share explanations."
    )

    st.markdown(
        """
        ### Main features

        - **Image-based study help:** Understand questions, formulas, and diagrams.
        - **Simple, step-by-step explanations:** Clear guidance without guessing.
        - **Follow-up conversations:** Ask for further clarification.
        - **Telegram integration:** Keep study notes accessible on your phone.
        """
    )

    st.caption(
        "AI answers can contain mistakes. "
        "Verify important work with your textbook or teacher."
    )