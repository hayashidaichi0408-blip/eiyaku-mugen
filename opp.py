import streamlit as st
from google import genai
from data import DATA
import json
import os
import requests
from streamlit_gsheets import GSheetsConnection
import pandas as pd

# ログアウト処理
def logout():
    st.session_state.connected = False
    st.session_state["user_info"] = None
    st.rerun()

# --- 接続設定 ---
conn = st.connection("gsheets", type=GSheetsConnection)

# --- データの読み書き（スプレッドシート専用版） ---

def load_notes():
    if "user_info" not in st.session_state:
        return pd.DataFrame()
    try:
        # スプレッドシートを読み込む
        df = conn.read(worksheet="Sheet1")
        
        if df is None or df.empty:
            return pd.DataFrame()

        # ログイン中のユーザーのメールアドレスを取得
        user_email = str(st.session_state["user_info"]["email"]).strip().lower()
        
        # 自分の一致するものだけを抽出
        user_df = df[df['email'].astype(str).str.strip().str.lower() == user_email]
        
        return user_df
    except Exception as e:
        st.error(f"データの読み込み中にエラーが発生しました: {e}")
        return pd.DataFrame()

def save_data_to_sheets(q, ans, advice, keypoint, source):
    try:
        # デバッグ用メッセージ
        # st.write("デバッグ: 保存開始") 
        df = conn.read(worksheet="Sheet1")
        
        new_row = pd.DataFrame([{
            "email": st.session_state["user_info"]["email"],
            "q": q,
            "ans": ans,
            "advice": advice,
            "keypoint": keypoint,
            "source": source
        }])
        
        updated_df = pd.concat([df, new_row], ignore_index=True)
        conn.update(worksheet="Sheet1", data=updated_df)
        st.toast("スプレッドシートに保存しました！")
    except Exception as e:
        import traceback
        st.error(f"保存エラーの詳細: {type(e).__name__}")
        st.code(traceback.format_exc())

# --- 認証設定 ---
def get_login_url():
    client_id = st.secrets["GOOGLE_CLIENT_ID"]
    redirect_uri = st.secrets["REDIRECT_URI"]
    scope = "https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile"
    url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"response_type=code&client_id={client_id}&"
        f"redirect_uri={redirect_uri}&scope={scope}&"
        f"access_type=offline&prompt=select_account"
    )
    return url

# ログイン状態の確認
if "connected" not in st.session_state:
    st.session_state.connected = False


if not st.session_state.connected:
    st.title("🚀 無限英訳サバイバル")
    st.write("学習を始めるにはGoogleアカウントでログインしてください。")
    
    # ログインボタン（リンク）を表示
    login_url = get_login_url()
    st.markdown(f'<a href="{login_url}" target="_blank" style="text-decoration:none; background-color:#4285F4; color:white; padding:12px 24px; border-radius:5px; font-weight:bold;">Googleでログインする</a>', unsafe_allow_html=True)
    
   # URLにcodeが含まれていたら「ログインボタンを押して戻ってきた」と判断
    if "code" in st.query_params:
        auth_code = st.query_params["code"]
        
        # --- 1. codeをトークンに交換する ---
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "code": auth_code,
            "client_id": st.secrets["GOOGLE_CLIENT_ID"],
            "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"], # Secretsにこれも必要！
            "redirect_uri": st.secrets["REDIRECT_URI"],
            "grant_type": "authorization_code",
        }
        
        try:
            # Googleに問い合わせ
            res = requests.post(token_url, data=data)
            tokens = res.json()
            access_token = tokens.get("access_token")

            # --- 2. アクセストークンを使ってユーザー情報を取得する ---
            user_info_res = requests.get(
                "https://www.googleapis.com/oauth2/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            user_info = user_info_res.json()

            # 本物の情報をセッションに保存！
            st.session_state.connected = True
            st.session_state["user_info"] = {
                "email": user_info.get("email"),
                "name": user_info.get("name")
            }
            
            # 復習ノートをロード
            st.session_state.saved_notes = load_notes()
            
            # URLをきれいにする
            st.query_params.clear()
            st.rerun()

        except Exception as e:
            st.error(f"認証に失敗しました: {e}")
    
    

# ユーザー情報の取得（ログインしている場合のみ）
if st.session_state.connected:
    user_email = st.session_state["user_info"]["email"]
    user_name = st.session_state["user_info"]["name"]
else:
    # ログインしていない時は仮の値を置くか、以降の処理を止める
    user_email = None
    user_name = None


# --- 復習ノートの保存・読み込み関数 (ユーザー別に修正) ---


# Gemini API設定
API_KEY = st.secrets["GEMINI_API_KEY"]
client = genai.Client(api_key=API_KEY)

st.set_page_config(page_title="無限英訳", layout="centered")

# --- 2. セッション状態の初期化 ---

# (以下、元のコードと同じ)
if 'cleared' not in st.session_state:
    st.session_state.cleared = {}
if 'max_q_idx' not in st.session_state:
    st.session_state.max_q_idx = 0

states = ['grade', 'level', 'chapter', 'section', 'q_idx', 'last_res']
for s in states:
    if s not in st.session_state:
        st.session_state[s] = None if s != 'q_idx' else 0

# --- 3. サイドバー ---
with st.sidebar:
    st.title("メニュー")
    st.write(f"👤 {user_name}") # 名前を表示
    mode = st.radio("モード選択", ["問題演習", "復習ノート"])
    
    if st.button("🚪 ログアウト"):
        logout()  # ← 「auth.」を消して、自作の logout() を呼ぶようにします

    st.divider()
    if st.button("🏠 最初に戻る"):
        for s in states: st.session_state[s] = None if s != 'q_idx' else 0
        st.session_state.last_res = None
        st.session_state.max_q_idx = 0
        st.rerun()

# --- 4. 画面遷移ロジック ---
# --- 4. 画面遷移ロジック ---
if mode == "復習ノート":
    st.title("📚 復習ノート")
    # 最新のデータをスプレッドシートから読み込む
    st.session_state.saved_notes = load_notes()
    notes = st.session_state.saved_notes
    
    notes = load_notes()

    # .empty を使うのが Pandas の正しいマナーです
   if notes.empty:
        st.info("まだ復習ノートにデータがありません。")
    else:
        # 1. pinned列がない場合に備えて補完（Pandas流の書き方）
        if 'pinned' not in notes.columns:
            notes['pinned'] = False
        else:
            notes['pinned'] = notes['pinned'].fillna(False)

        # 2. お気に入り(pinned=True)を上に並べ替え
        notes = notes.sort_values(by='pinned', ascending=False)

        st.caption(f"現在 {len(notes)} 問保存されています。📌マークを付けると一番上に表示されます。")

        # 3. データの表示ループ (notes.iterrows() を使うのが正解)
        for index, note in notes.iterrows():
            pin_icon = "📌 " if note['pinned'] else ""
            
            with st.expander(f"{pin_icon}{note['q']}"):
                st.caption(f"出典: {note['source']}")

                # --- お気に入りボタン ---
                # 注: 更新処理は複雑になるので、まずは見た目と rerun だけで構成
                btn_label = "📌 お気に入り解除" if note['pinned'] else "📍 お気に入りに追加"
                if st.button(btn_label, key=f"pin_{index}"):
                    # ここでスプレッドシートを更新する処理が必要ですが、
                    # ひとまず「動く」状態にするためにトースト表示だけにします
                    st.toast("お気に入り状態の保存は、スプレッドシート連携の次のステップで実装しましょう！")
                    st.rerun()

                st.info(f"**問題（和訳対象）:**\n{note['q']}")
                st.success(f"**正解例:**\n{note['ans']}")

                tab1, tab2 = st.tabs(["💡 解説・添削", "📌 ポイント"])
                with tab1:
                    st.write(note['advice'])
                with tab2:
                    st.write(note['keypoint'])

                st.divider()

                # --- 削除ボタン ---
                if st.button(f"🗑️ 削除", key=f"del_{index}"):
                    # スプレッドシートから行を消すのは少し工夫がいるので、まずは案内を出す形にします
                    st.warning("スプレッドシートから直接データを削除してください。アプリからの削除機能は開発中です。")
    st.stop()

elif mode == "問題演習":
    # 学年選択
    if st.session_state.grade is None:
        st.title("学年選択")
        for g in DATA.keys():
            if st.button(g, use_container_width=True):
                st.session_state.grade = g
                st.rerun()

    # 難易度選択
    elif st.session_state.level is None:
        st.title("難易度選択")
        if st.button("⬅️ 学年選択に戻る"):
            st.session_state.grade = None
            st.rerun()

        grade_data = DATA[st.session_state.grade]
        for lv in grade_data.keys():
            # そのレベル内のすべての章がクリアされているかチェック
            chapters = grade_data[lv].keys()
            is_lv_cleared = all(f"{lv}_{ch}" in st.session_state.cleared for ch in chapters)

            label = f"✅ {lv}" if is_lv_cleared else lv
            if st.button(label, use_container_width=True):
                st.session_state.level = lv
                st.rerun()

    # 章選択
    elif st.session_state.chapter is None:
        st.title("章選択")
        if st.button("⬅️ 難易度選択に戻る"):
            st.session_state.level = None
            st.rerun()

        level_data = DATA[st.session_state.grade][st.session_state.level]
        for ch in level_data.keys():
            # その章内のすべての節がクリアされているかチェック
            sections = level_data[ch].keys()
            is_ch_cleared = all(
                f"{st.session_state.grade}_{st.session_state.level}_{ch}_{sec}" in st.session_state.cleared for sec in
                sections)

            if is_ch_cleared:
                st.session_state.cleared[f"{st.session_state.level}_{ch}"] = True

            label = f"✅ {ch}" if is_ch_cleared else ch
            if st.button(label, use_container_width=True):
                st.session_state.chapter = ch
                st.rerun()

    # 節選択
    elif st.session_state.section is None:
        st.title("節選択")
        if st.button("⬅️ 章選択に戻る"):
            st.session_state.chapter = None
            st.rerun()

        section_data = DATA[st.session_state.grade][st.session_state.level][st.session_state.chapter]
        for sec in section_data.keys():
            is_sec_cleared = f"{st.session_state.grade}_{st.session_state.level}_{st.session_state.chapter}_{sec}" in st.session_state.cleared

            label = f"✅ {sec}" if is_sec_cleared else sec
            if st.button(label, use_container_width=True):
                st.session_state.section = sec
                st.session_state.q_idx = 0
                st.session_state.max_q_idx = 0
                st.session_state.last_res = None
                st.rerun()

    # --- 5. 問題演習メイン ---
    else:
        if st.session_state.section is None:
            st.rerun()

        level = st.session_state.level
        questions = DATA[st.session_state.grade][level][st.session_state.chapter][st.session_state.section]
        q_idx = st.session_state.q_idx
        current_q = questions[q_idx]

        # ナビゲーション
        col_back1, col_back2, col_next = st.columns([1, 1, 1])
        with col_back1:
            if st.button("⬅️ 節選択へ"):
                st.session_state.section = None
                st.session_state.last_res = None
                st.rerun()
        with col_back2:
            if q_idx > 0:
                if st.button("⬅️ 前の問題"):
                    st.session_state.q_idx -= 1
                    st.session_state.last_res = None
                    st.rerun()
        with col_next:
            if q_idx < st.session_state.max_q_idx and q_idx + 1 < len(questions):
                if st.button("次の問題へ ➡️"):
                    st.session_state.q_idx += 1
                    st.session_state.last_res = None
                    st.rerun()

        st.subheader(f"{st.session_state.section} (Q{q_idx + 1}/{len(questions)})")
        st.progress((q_idx + 1) / len(questions))
        st.info(f"**和訳対象:**\n### {current_q}")
        user_input = st.text_input("英文を入力してください:", key=f"input_{q_idx}")

        if st.button("採点・解説", type="primary"):
            if not user_input:
                st.warning("英文を入力してください。")
            else:
                with st.spinner("採点中..."):
                    prompt = f"""
                    あなたは「世界一わかりやすい英語の先生」です。
                    専門用語は極力使わず、中学生が直感的に理解できる言葉で教えてください。
                    be動詞や一般動詞などの一般的な用語は使用OKです。
                    無駄な言葉（「すごいね」など）を省き、必要なことをわかりやすく説明してください。
                    英訳の正答例は解説の中に直接書かないでください。
                    keypointでは示されたcurrent_qからのみ考え,生徒の解答は全く考慮せず（生徒が間違えた点を重点的に解説する必要は全くない。current_qでもっとも大事だと思われる文法的知識を二つ解説する）一般的に問題を解くためにもっとも重要だと思われる文法的知識をcurrent_qから読み取り詳しく普遍的に使えるように解説してください。

                    問題文: {current_q}
                    生徒の回答: {user_input}

                    【回答の構成ルール】
                    1. SCORE: 2〜10の点数。
                    2. IMPROVE: 添削結果とルールの解説。難しい言葉には補足を入れてください。
                    3. KEYPOINT: 【2. KEYPOINT（重要知識の抽出）】
★重要：ここでは生徒の回答は一切無視してください。
問題文（{current_q}）と正解（{current_q}の標準的な英訳）を分析し、
この問題を解くために必要な「普遍的な文法知識」を2つだけ詳しく解説してください。
（例：不定詞の形容詞的用法、関係代名詞の目的格など）
                    4. VOCAB: 単語の意味。
                    5. ANSWER: 最も自然な正解例。これが生徒の解答とほとんど一致している場合は合格（８点以上）にしてください。ほとんど同じと言っても意味が違ったり文法的に間違っていたら不合格にしてください。

                    【出力形式】
                    SCORE: [数字]
                    IMPROVE: [解説]
                    KEYPOINT: [考え方のコツ]
                    VOCAB: [単語リスト]
                    ANSWER: [正答]
                    """
                    try:
                        response = client.models.generate_content(model="models/gemini-2.5-flash-lite", contents=prompt)
                        raw = response.text


                        def extract(text, start_label, end_label=None):
                            if start_label not in text: return "解析中..."
                            start = text.find(start_label) + len(start_label)
                            if end_label and end_label in text:
                                end = text.find(end_label, start)
                                return text[start:end].strip()
                            return text[start:].strip()


                        score_raw = extract(raw, "SCORE:", "IMPROVE:")
                        score_str = ''.join(filter(str.isdigit, score_raw))
                        score_val = int(score_str) if score_str else 0

                        st.session_state.last_res = {
                            "score": min(score_val, 10),
                            "improve": extract(raw, "IMPROVE:", "KEYPOINT:"),
                            "keypoint": extract(raw, "KEYPOINT:", "VOCAB:"),
                            "vocab": extract(raw, "VOCAB:", "ANSWER:"),
                            "answer": extract(raw, "ANSWER:")
                        }
                        st.rerun()
                    except Exception as e:
                        st.error(f"エラー: {e}")

        # 結果表示
        if st.session_state.last_res:
            res = st.session_state.last_res
            if res["score"] >= 8:
                st.success(f"スコア: {res['score']} / 10 (合格)")
                st.session_state.max_q_idx = max(st.session_state.max_q_idx, q_idx + 1)
            else:
                st.error(f"スコア: {res['score']} / 10 (不合格)")

            st.markdown(f"**改善点・添削解説:**\n{res['improve']}")
            st.warning(f"**💡 文法・出題のポイント:**\n{res['keypoint']}")

            with st.expander("重要単語を表示"):
                st.write(res['vocab'])
            with st.expander("正答例を表示"):
                st.code(res['answer'], language="text")

            if st.button("🌟 復習ノートに保存"):
                is_already_saved = any(note['q'] == current_q for note in st.session_state.saved_notes)
                if is_already_saved:
                    st.warning("⚠️ この問題は既に保存されています。")
                else:
                    # スプレッドシートに保存する関数を呼び出す
                    save_data_to_sheets(
                        current_q, 
                        res['answer'], 
                        res['improve'], 
                        res['keypoint'],
                        f"{st.session_state.grade} > {st.session_state.level} > {st.session_state.chapter}"
                    )
                    # 保存後に画面上のリストも最新にする
                    st.session_state.saved_notes = load_notes()

            if res["score"] >= 8:
                if q_idx + 1 < len(questions):
                    if st.button("合格！次の問題へ進む ➡️", key="next_after_win"):
                        st.session_state.q_idx += 1
                        st.session_state.last_res = None
                        st.rerun()
                else:
                    sec_key = f"{st.session_state.grade}_{st.session_state.level}_{st.session_state.chapter}_{st.session_state.section}"
                    st.session_state.cleared[sec_key] = True
                    st.balloons()
                    st.success("🎉 この節のすべての問題をクリアしました！")
                    if st.button("🎉 章選択に戻る"):
                        st.session_state.section = None
                        st.rerun()
#  https://english-opp-lczytel8teegbpzptqgwe9.streamlit.app/
#https://eiyaku-mugen.streamlit.app/
