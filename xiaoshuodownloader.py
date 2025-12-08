
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
import datetime  # <--- 新增：用于计算Cookie过期时间
import extra_streamlit_components as stx  # <--- 新增：用于管理Cookie

# ==========================================
# 1. 基础引擎
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
# 2. 99小说网 (保持原样)
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

            target_item = None;
            target_title = "";
            target_href = "";
            target_author = "佚名"
            for item in soup.select(".booklist_a .list_a .main"):
                link = item.find('a')
                if not link: continue
                raw_title = link.get_text().strip()
                if self.validate_title(keyword, raw_title):
                    target_item = item;
                    target_title = raw_title;
                    target_href = link['href']
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
# 3. 00小说网 (保留代码但暂不使用)
# ==========================================
class ZeroShu_Engine(BaseEngine):
    def __init__(self):
        super().__init__()
        self.source_name = "00小说网"
        self.base_url = "http://m.00shu.la" 
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "http://m.00shu.la/",
            "Origin": "http://m.00shu.la",
            "Content-Type": "application/x-www-form-urlencoded"
        }

    async def run(self, session, keyword):
        # ... (此处省略具体逻辑，保持你之前的代码结构不变，为了节省篇幅我没重复贴中间逻辑，类结构保留即可) ...
        # 如果你之前这部分是完整的，保留即可，不用改动
        return False, None, [] 


# ==========================================
# 4. 笔趣阁 (新增：专治找不到书)
# ==========================================
class BiQuGe_Engine(BaseEngine):
    def __init__(self):
        super().__init__()
        self.source_name = "笔趣阁"
        self.base_url = "https://www.bqgka.com"

    async def run(self, session, keyword):
        logs = []
        try:
            self.log(logs, f"🚀 搜索: {keyword}")
            async with session.get(f"{self.base_url}/s?q={urllib.parse.quote(keyword)}", headers=self.headers) as resp:
                soup = BeautifulSoup(await resp.text(errors='ignore'), 'html.parser')

            target_data = {}
            found = False
            for item in soup.select("h4.bookname a"):
                title = item.get_text().strip()
                if self.validate_title(keyword, title):
                    target_data = {"title": title, "href": item['href'], "author": "未知"}
                    found = True
                    break
            
            if not found:
                self.log(logs, "❌ 未找到")
                return False, None, logs

            self.log(logs, f"✅ 锁定: 《{target_data['title']}》")
            full_url = self.base_url + target_data['href']
            
            return True, {
                "type": "link", 
                "title": target_data['title'],
                "author": target_data['author'],
                "url": full_url
            }, logs
        except Exception as e:
            self.log(logs, f"❌ 异常: {e}")
            return False, None, logs


# ==========================================
# 5. Z-Library 引擎
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
# 6. 搜索调度逻辑
# ==========================================
async def search_race_mode(keyword, zlib_creds):
    # ✅ 修改：加入 BiQuGe_Engine，暂时注释掉 ZeroShu_Engine
    engines = [JJJXSW_Engine(), BiQuGe_Engine()] 
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
# 7. UI 部分
# ==========================================

st.set_page_config(page_title="全能赛马下载器", page_icon="🦄", layout="centered")

# 初始化 Cookie 管理器 (放在 set_page_config 之后)
cookie_manager = stx.CookieManager()

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 0rem !important;
        padding-bottom: 1rem !important;
    }
    .stButton>button{width:100%;border-radius:8px;font-weight:bold}
    .success-box{padding:15px;background:#e6fffa;border:1px solid #38b2ac;color:#234e52;border-radius:8px}
    .link-box{padding:15px;background:#ebf8ff;border:1px solid #4299e1;color:#2b6cb0;border-radius:8px;text-align:center;}
    .link-box a {color: #2b6cb0; font-weight: bold; font-size: 1.2em; text-decoration: none;}
    </style>
    """,
    unsafe_allow_html=True)


st.title("")
st.caption("并发检索：99小说 | 笔趣阁 | Z-Library")

# === 侧边栏：Cookie 账号管理 ===
with st.sidebar:
    st.header("🔑 Z-Library")
    
    # 1. 读取 Cookie
    cookies = cookie_manager.get_all()
    cookie_email = cookies.get("zlib_email", "") 
    cookie_pass = cookies.get("zlib_pass", "")

    # 2. 显示输入框
    input_email = st.text_input("Email", value=cookie_email, key="z_email_input")
    input_pass = st.text_input("Password", value=cookie_pass, type="password", key="z_pass_input")

    # 3. 保存按钮 (30天有效期)
    if st.button("💾 记住我的账号"):
        expires = datetime.datetime.now() + datetime.timedelta(days=30)
        cookie_manager.set("zlib_email", input_email, expires_at=expires)
        cookie_manager.set("zlib_pass", input_pass, expires_at=expires)
        st.success("已保存到设备！")
        time.sleep(1)
        st.rerun()

    # 4. 清除按钮
    if st.button("🗑️ 忘记账号"):
        cookie_manager.delete("zlib_email")
        cookie_manager.delete("zlib_pass")
        st.rerun()

# === 主界面逻辑 ===
keyword = st.text_input("书名", placeholder="例如：可怜的社畜")
if st.button("🚀 极速检索", type="primary"):
    if not keyword:
        st.warning("请输入书名")
    else:
        st.info("🔎 全网并发检索中...")
        res = asyncio.run(search_race_mode(keyword, {'email': input_email, 'password': input_pass}))

        if res["success"]:
            d = res['data']

            # 情况 A: 链接 (Z-Lib 或 笔趣阁)
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
                if d['filename'].endswith(".pdf"):
                    mime = "application/pdf"
                elif d['filename'].endswith(".epub"):
                    mime = "application/epub+zip"
                elif d['filename'].endswith(".txt"):
                    mime = "text/plain"

                c1, c2 = st.columns(2)
                c1.download_button(f"📥 下载 ({d['filename'].split('.')[-1]})", d['content'], d['filename'], mime=mime)

                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED, False) as zf:
                    zf.writestr(d['filename'], d['content'])
                c2.download_button("📦 下载ZIP", buf.getvalue(), d['filename'] + ".zip", "application/zip")

        else:
            st.error("😭 全网未找到资源")

        with st.expander("查看执行日志"):
            for m in res["logs"]: st.text(m)

