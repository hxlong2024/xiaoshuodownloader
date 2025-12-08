import streamlit as st
import aiohttp
import asyncio
from bs4 import BeautifulSoup
import re
import zipfile
import io
import time
import urllib.parse
import mimetypes
import datetime
import extra_streamlit_components as stx

# ==========================================
# 1. 基础引擎 (保持不变)
# ==========================================

class BaseEngine:
    def __init__(self):
        self.source_name = "未知源"
        # 模拟最新 Chrome
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }

    def log(self, msgs, text):
        msgs.append(f"[{self.source_name}] {text}")

    def clean_filename(self, text):
        return re.sub(r'[\\/*?:"<>|]', "", text).strip()

    def validate_title(self, user_keyword, site_title):
        def clean(s): return re.sub(r'[^\w\u4e00-\u9fa5]', '', s).lower()
        return clean(user_keyword) in clean(site_title)

    async def run(self, session, keyword):
        raise NotImplementedError

# ==========================================
# 2. 99小说网 (保持不变)
# ==========================================
class JJJXSW_Engine(BaseEngine):
    def __init__(self):
        super().__init__()
        self.source_name = "99小说网"
        self.base_url = "https://m.jjjxsw.com"
        self.headers["Referer"] = "https://m.jjjxsw.com/"

    async def run(self, session, keyword):
        logs = []
        try:
            self.log(logs, f"🚀 搜索: {keyword}")
            async with session.post(f"{self.base_url}/e/search/index.php",
                                    data={"keyboard": keyword, "Submit22": "搜索", "show": "title"},
                                    headers=self.headers) as resp:
                soup = BeautifulSoup(await resp.text(encoding='utf-8', errors='ignore'), 'html.parser')

            target_item = None; target_title = ""; target_href = ""; target_author = "佚名"
            for item in soup.select(".booklist_a .list_a .main"):
                link = item.find('a')
                if not link: continue
                raw_title = link.get_text().strip()
                if self.validate_title(keyword, raw_title):
                    target_item = item; target_title = raw_title; target_href = link['href']
                    for span in item.find_all('span'):
                        if "作者" in span.get_text(): target_author = span.get_text().split(":")[-1].strip(); break
                    break

            if not target_item: return False, None, logs
            self.log(logs, f"✅ 匹配: 《{target_title}》")

            async with session.get(self.base_url + target_href, headers=self.headers) as resp:
                intro_soup = BeautifulSoup(await resp.text(encoding='utf-8', errors='ignore'), 'html.parser')
            confirm_url = None
            sso = intro_soup.select_one(".sso_d")
            if sso:
                for a in sso.find_all('a'):
                    if "下载" in a.get_text(): confirm_url = a['href']; break
            if not confirm_url:
                t = intro_soup.find('a', string=re.compile("下载"))
                if t: confirm_url = t['href']
            if not confirm_url: return False, None, logs
            if not confirm_url.startswith("http"): confirm_url = self.base_url + confirm_url

            async with session.get(confirm_url, headers=self.headers) as resp:
                confirm_soup = BeautifulSoup(await resp.text(encoding='utf-8', errors='ignore'), 'html.parser')
            real_link = confirm_soup.find('a', id='id0') or confirm_soup.find('a', href=re.compile(r'doaction\.php'))
            if not real_link: return False, None, logs
            real_url = real_link['href']
            if not real_url.startswith("http"): real_url = self.base_url + real_url

            self.log(logs, "⬇️ 下载中...")
            async with session.get(real_url, headers=self.headers) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    fname = f"{self.clean_filename(target_title)} by {self.clean_filename(target_author)}.txt"
                    return True, {"filename": fname, "author": target_author, "content": content}, logs
            return False, None, logs
        except Exception as e:
            self.log(logs, f"❌ 异常: {e}");
            return False, None, logs

# ==========================================
# 3. Z-Library 引擎
# ==========================================
class ZLibrary_Engine(BaseEngine):
    def __init__(self, email, password):
        super().__init__()
        self.source_name = "Z-Library"
        self.base_url = "https://en.zlib.li"
        self.email = email
        self.password = password

    async def login(self, session, logs):
        if not self.email: return False
        self.log(logs, "🔑 正在登录...")
        try:
            h = self.headers.copy();
            h["Origin"] = self.base_url;
            h["Referer"] = f"{self.base_url}/login"
            payload = {"email": self.email, "password": self.password, "site_mode": "books", "action": "login",
                       "redirectUrl": self.base_url + "/"}
            async with session.post(f"{self.base_url}/", data=payload, headers=h) as resp:
                text = await resp.text()
                if 'id="loginForm"' in text or "validation-error" in text:
                    self.log(logs, "❌ 登录失败")
                    return False
                self.log(logs, "🔓 登录成功")
                return True
        except Exception as e:
            self.log(logs, f"❌ 登录异常: {e}");
            return False

    async def run(self, session, keyword):
        logs = []
        if not await self.login(session, logs): return False, None, logs

        try:
            self.log(logs, f"🚀 搜索: {keyword}")
            async with session.get(f"{self.base_url}/s/", params={"q": keyword}, headers=self.headers) as resp:
                soup = BeautifulSoup(await resp.text(errors='ignore'), 'html.parser')

            target_item = None
            target_data = {}

            for item in soup.find_all('z-bookcard'):
                t_div = item.find('div', slot='title')
                title = t_div.get_text().strip() if t_div else ""
                href = item.get('href')

                if self.validate_title(keyword, title) and href:
                    target_item = item
                    target_data = {"title": title, "href": href.strip()}
                    a_div = item.find('div', slot='author')
                    target_data['author'] = a_div.get_text().strip() if a_div else "佚名"
                    break

            if not target_item:
                self.log(logs, "❌ 未找到匹配书籍")
                return False, None, logs

            detail_url = urllib.parse.urljoin(self.base_url, target_data['href'])
            self.log(logs, f"✅ 锁定: 《{target_data['title']}》")
            self.log(logs, f"🔗 生成详情页链接: {detail_url}")

            return True, {
                "type": "link", 
                "title": target_data['title'],
                "author": target_data['author'],
                "url": detail_url
            }, logs

        except Exception as e:
            self.log(logs, f"❌ 异常: {e}");
            return False, None, logs

# ==========================================
# 4. 搜索调度逻辑
# ==========================================
async def search_race_mode(keyword, zlib_creds):
    engines = [JJJXSW_Engine()] 
    if zlib_creds['email']: engines.append(ZLibrary_Engine(zlib_creds['email'], zlib_creds['password']))

    start = time.time()
    all_logs = []

    timeout = aiohttp.ClientTimeout(total=15)
    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        tasks = [asyncio.create_task(e.run(session, keyword)) for e in engines]
        for t, e in zip(tasks, engines): t.set_name(e.source_name)

        pending = set(tasks)
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                success, result, logs = await task
                all_logs.extend(logs)
                if success and result:
                    for p in pending: p.cancel()
                    return {"success": True, "source": task.get_name(), "data": result, "logs": all_logs,
                            "time": time.time() - start}
    return {"success": False, "logs": all_logs, "time": time.time() - start}

# ==========================================
# 5. UI 部分 (全新重构版)
# ==========================================

st.set_page_config(page_title="全能赛马下载器", page_icon="🦄", layout="centered")

# 初始化 Cookie 管理器
cookie_manager = stx.CookieManager()

st.markdown(
    """
    <style>
    .block-container {padding-top: 0rem !important; padding-bottom: 1rem !important;}
    .stButton>button{width:100%;border-radius:8px;font-weight:bold}
    .success-box{padding:15px;background:#e6fffa;border:1px solid #38b2ac;color:#234e52;border-radius:8px}
    .link-box{padding:15px;background:#ebf8ff;border:1px solid #4299e1;color:#2b6cb0;border-radius:8px;text-align:center;}
    .link-box a {color: #2b6cb0; font-weight: bold; font-size: 1.2em; text-decoration: none;}
    </style>
    """,
    unsafe_allow_html=True)

st.title("")
st.caption("并发检索：99小说 | Z-Library")

# === 侧边栏：全新账号逻辑 ===
with st.sidebar:
    st.header("🔑 Z-Library 账号")

    # 1. 静默读取 Cookie
    # get_all() 即使还没加载完返回 None 也没关系，我们不强求
    cookies = cookie_manager.get_all()
    saved_email = cookies.get("zlib_email") if cookies else None
    saved_pass = cookies.get("zlib_pass") if cookies else None

    # 2. 状态显示区 (代替输入框作为主要展示)
    if saved_email:
        # 🟢 状态：已登录
        st.success(f"✅ 已保存账号: \n{saved_email}")
        st.caption("搜索时将自动使用此账号。")
        
        # 只有点击展开才显示修改框，避免视觉干扰
        with st.expander("修改/更新账号"):
             with st.form("update_form"):
                new_email = st.text_input("新 Email")
                new_pass = st.text_input("新 Password", type="password")
                if st.form_submit_button("更新保存"):
                    expires = datetime.datetime.now() + datetime.timedelta(days=30)
                    cookie_manager.set("zlib_email", new_email, expires_at=expires, key="upd_email")
                    cookie_manager.set("zlib_pass", new_pass, expires_at=expires, key="upd_pass")
                    st.rerun() # 这里Rerun没关系，因为是用户点击保存
        
        if st.button("🚪 退出登录"):
            cookie_manager.delete("zlib_email", key="del_e")
            cookie_manager.delete("zlib_pass", key="del_p")
            st.rerun()
            
    else:
        # 🔴 状态：未登录
        st.warning("⚠️ 未检测到保存的账号")
        
        # 使用 Form 表单来保存，避免刷新打断
        with st.form("login_form"):
            temp_email = st.text_input("Email")
            temp_pass = st.text_input("Password", type="password")
            
            # 两个按钮：一个仅本次使用，一个保存
            c1, c2 = st.columns(2)
            is_save = c1.form_submit_button("💾 保存账号")
            
            if is_save:
                if temp_email and temp_pass:
                    expires = datetime.datetime.now() + datetime.timedelta(days=30)
                    cookie_manager.set("zlib_email", temp_email, expires_at=expires, key="new_e")
                    cookie_manager.set("zlib_pass", temp_pass, expires_at=expires, key="new_p")
                    st.success("已保存！")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("请填写完整")

# === 主界面逻辑 ===
keyword = st.text_input("书名", placeholder="例如：可怜的社畜")

if st.button("🚀 极速检索", type="primary"):
    if not keyword:
        st.warning("请输入书名")
    else:
        # 🧠 核心逻辑：智能选择账号
        # 优先使用 Cookie 里的，如果没有，就用刚才输入框里的（如果有的话）
        # 这里需要注意：如果用户没保存，输入框在 form 里，外面拿不到 form 里的值
        # 所以：如果未登录，必须点保存才能用 Z-Lib，或者在 form 外面再提供临时输入？
        # 简化逻辑：Z-Lib 必须登录才能用。
        
        final_email = saved_email
        final_pass = saved_pass
        
        # 如果没有 Cookie，尝试读取 session_state 里的临时值 (如果有)
        # 但因为上面用了 form，最稳妥的方式是要求用户必须保存账号才能用 Zlib
        # 或者 Zlib 引擎会检测，如果 email 为空，会自动跳过
        
        st.info("🔎 全网并发检索中...")
        res = asyncio.run(search_race_mode(keyword, {'email': final_email, 'password': final_pass}))

        if res["success"]:
            d = res['data']

            # 情况 A: 链接 (Z-Lib)
            if d.get("type") == "link":
                st.markdown(
                    f"""
                    <div class='link-box'>
                        <h3>🕵️‍♂️ 已找到书籍/详情页</h3>
                        <p><b>{d['title']}</b><br>作者: {d['author']}</p>
                        <hr style="margin:10px 0; border:0; border-top:1px solid #bbeeef;">
                        <p>请点击下方链接去浏览器阅读或下载：</p>
                        <a href="{d['url']}" target="_blank">👉 点击打开: {d['title']} 👈</a>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                st.text_input("或复制此链接:", d['url'])
                st.caption(f"来源: {res['source']} (耗时 {res['time']:.2f}s)")

            # 情况 B: 文件 (99小说网)
            elif "content" in d:
                st.markdown(
                    f"<div class='success-box'><h3>✅ 文件获取成功!</h3><b>{d['filename']}</b><br>源: {res['source']} ({res['time']:.2f}s)</div>",
                    unsafe_allow_html=True)

                mime = "application/octet-stream"
                if d['filename'].endswith(".pdf"): mime = "application/pdf"
                elif d['filename'].endswith(".epub"): mime = "application/epub+zip"
                elif d['filename'].endswith(".txt"): mime = "text/plain"

                c1, c2 = st.columns(2)
                c1.download_button(f"📥 下载 ({d['filename'].split('.')[-1]})", d['content'], d['filename'], mime=mime)

                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED, False) as zf:
                    zf.writestr(d['filename'], d['content'])
                c2.download_button("📦 下载ZIP", buf.getvalue(), d['filename'] + ".zip", "application/zip")

        else:
            st.error("😭 全网未找到资源")
            if not final_email:
                st.warning("提示：Z-Library 需要先在侧边栏【保存账号】才能搜索。")

        with st.expander("查看执行日志"):
            for m in res["logs"]: st.text(m)
