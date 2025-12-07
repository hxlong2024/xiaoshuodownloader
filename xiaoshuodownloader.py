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
# 2. 99小说网 (保持原样 - 提供文件下载)
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
                    # 注意：这里返回 content，表示是文件流
                    return True, {"filename": fname, "author": target_author, "content": content}, logs
            return False, None, logs
        except Exception as e:
            self.log(logs, f"❌ 异常: {e}");
            return False, None, logs


# ==========================================
# 3. 00小说网 (终极修复：先访问主页拿Cookie)
# ==========================================
class ZeroShu_Engine(BaseEngine):
    def __init__(self):
        super().__init__()
        self.source_name = "00小说网"
        # 强制使用 http，避开 https 证书问题
        self.base_url = "http://m.00shu.la" 
        
        # 模拟普通电脑浏览器的头
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "http://m.00shu.la/",
            "Origin": "http://m.00shu.la",
            "Content-Type": "application/x-www-form-urlencoded"
        }

    async def run(self, session, keyword):
        logs = []
        try:
            # === 第一步：先访问首页，为了获取 Cookie ===
            # 很多网站防爬虫策略是：没有首页的 Cookie，就不允许搜索
            try:
                await session.get(self.base_url, headers=self.headers)
            except:
                pass # 就算首页慢，也尝试继续，万一不需要呢

            # === 第二步：带着 Cookie 去搜索 ===
            self.log(logs, f"🚀 搜索: {keyword}")
            async with session.post(f"{self.base_url}/s.php", 
                                    data={"searchkey": keyword, "type": "articlename"},
                                    headers=self.headers) as resp:
                # 00小说网有时返回的是乱码，尝试用 gbk 或 utf-8 解码
                content = await resp.read()
                # 尝试自动检测编码，通常是 utf-8
                html = content.decode('utf-8', errors='ignore')
                soup = BeautifulSoup(html, 'html.parser')
            
            target_title = ""; target_href = ""; target_author = "佚名"; found = False
            
            # 打印一下找到多少个结果，方便调试
            items = soup.select(".searchresult .sone")
            
            for item in items:
                a = item.find('a')
                if not a: continue
                raw_title = a.get_text().strip()
                
                # 验证标题
                if self.validate_title(keyword, raw_title):
                    target_title = raw_title
                    target_href = a['href']
                    span = item.find('span', class_='author')
                    if span: target_author = span.get_text().strip()
                    found = True
                    break

            if not found: 
                # 如果没找到，有时候是因为网站把你重定向到了详情页（如果是唯一结果）
                # 检查是不是直接跳到了书名页
                meta_title = soup.select_one("meta[property='og:title']")
                if meta_title and self.validate_title(keyword, meta_title['content']):
                     # 这里处理一下唯一结果直接跳转的情况（预留逻辑，通常00shu不会）
                     pass
                
                self.log(logs, "❌ 未找到 (或被反爬拦截)")
                return False, None, logs
                
            self.log(logs, f"✅ 匹配: 《{target_title}》")

            # === 第三步：处理详情页链接 ===
            # 补全链接
            if target_href.startswith("/"):
                detail_url = self.base_url + target_href
            elif not target_href.startswith("http"):
                detail_url = f"{self.base_url}/{target_href}"
            else:
                detail_url = target_href
            
            # 强制 http
            detail_url = detail_url.replace("https://", "http://")
            
            async with session.get(detail_url, headers=self.headers) as resp:
                detail_soup = BeautifulSoup(await resp.text(errors='ignore'), 'html.parser')
            
            # === 第四步：找下载也 ===
            inter_href = None
            btn_list = detail_soup.find(id="btnlist")
            if btn_list:
                l = btn_list.find('a', string=re.compile("下载"))
                if l: inter_href = l['href']
            
            if not inter_href: return False, None, logs
            
            # 补全下载页链接
            inter_url = urllib.parse.urljoin(detail_url, inter_href)
            inter_url = inter_url.replace("https://", "http://")

            async with session.get(inter_url, headers=self.headers) as resp:
                down_soup = BeautifulSoup(await resp.text(errors='ignore'), 'html.parser')
            
            # === 第五步：找文件链接 ===
            file_link = down_soup.find('a', href=re.compile(r'\.(txt|zip|rar)$', re.IGNORECASE))
            if not file_link: file_link = down_soup.find('a', string=re.compile("下载"), href=lambda h: h and ('txt' in h or 'down' in h))
            
            if not file_link: return False, None, logs
            real_url = file_link['href']
            real_url = urllib.parse.urljoin(inter_url, real_url)
            real_url = real_url.replace("https://", "http://")

            self.log(logs, "⬇️ 下载中...")
            async with session.get(real_url, headers=self.headers) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    ext = ".txt"
                    if content[:2] == b'PK': ext = ".zip"
                    elif content[:2] == b'Rar': ext = ".rar"
                    fname = f"{self.clean_filename(target_title)} by {self.clean_filename(target_author)}{ext}"
                    return True, {"filename": fname, "author": target_author, "content": content}, logs
            return False, None, logs
        except Exception as e:
            self.log(logs, f"❌ 异常: {e}")
            return False, None, logs


# ==========================================
# 4. Z-Library 引擎 (V9.0 直达详情页版)
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
            # 1. 搜索
            self.log(logs, f"🚀 搜索: {keyword}")
            async with session.get(f"{self.base_url}/s/", params={"q": keyword}, headers=self.headers) as resp:
                soup = BeautifulSoup(await resp.text(errors='ignore'), 'html.parser')

            target_item = None
            target_data = {}

            # 解析搜索结果
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

            # 2. 获取详情页链接并返回
            # 强制拼接完整 URL，确保是 https://...
            detail_url = urllib.parse.urljoin(self.base_url, target_data['href'])

            self.log(logs, f"✅ 锁定: 《{target_data['title']}》")
            self.log(logs, f"🔗 生成详情页链接: {detail_url}")

            # === 修改处：不再下载，直接返回 URL ===
            # 我们返回一个特殊的字典，没有 'content' 字段，但有 'url'
            return True, {
                "type": "link",  # 标记这是个链接
                "title": target_data['title'],
                "author": target_data['author'],
                "url": detail_url
            }, logs

        except Exception as e:
            self.log(logs, f"❌ 异常: {e}");
            return False, None, logs


# ==========================================
# 5. UI 部分 (适配链接显示)
# ==========================================
async def search_race_mode(keyword, zlib_creds):
    engines = [JJJXSW_Engine()]    #, ZeroShu_Engine()
    if zlib_creds['email']: engines.append(ZLibrary_Engine(zlib_creds['email'], zlib_creds['password']))

    start = time.time()
    all_logs = []

    # ================= 修改开始 =================
    # 1. 设置超时时间为 15 秒 (防止网站慢导致报错)
    timeout = aiohttp.ClientTimeout(total=15)
    
    # 2. 忽略 SSL 证书验证 (很多小说站证书是过期的，设为 False 可以强制连接)
    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
    # ================= 修改结束 =================
    
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



st.set_page_config(page_title="全能赛马下载器", page_icon="🦄", layout="centered")
st.markdown(
    """
    <style>
    /* 1. 核心代码：减少顶部空白 */
    .block-container {
        padding-top: 0rem !important;  /* 数字越小，离顶部越近，默认大概是 5rem */
        padding-bottom: 1rem !important;
    }

    /* 2. 你原本的按钮和提示框样式 */
    .stButton>button{width:100%;border-radius:8px;font-weight:bold}
    .success-box{padding:15px;background:#e6fffa;border:1px solid #38b2ac;color:#234e52;border-radius:8px}
    .link-box{padding:15px;background:#ebf8ff;border:1px solid #4299e1;color:#2b6cb0;border-radius:8px;text-align:center;}
    .link-box a {color: #2b6cb0; font-weight: bold; font-size: 1.2em; text-decoration: none;}
    </style>
    """,
    unsafe_allow_html=True)


st.title("")
st.caption("并发检索：99小说 | 00小说 | Z-Library (提供详情页直链)")

with st.sidebar:
    st.header("🔑 Z-Library")
    z_email = st.text_input("Email");
    z_pass = st.text_input("Password", type="password")

keyword = st.text_input("书名", placeholder="例如：可怜的社畜")
if st.button("🚀 极速检索", type="primary"):
    if not keyword:
        st.warning("请输入书名")
    else:
        st.info("🔎 全网并发检索中...")
        res = asyncio.run(search_race_mode(keyword, {'email': z_email, 'password': z_pass}))

        if res["success"]:
            d = res['data']

            # === 分支判断：是直接下载的文件，还是 ZLib 的链接？ ===

            # 情况 A: 这是一个链接 (Z-Library)
            if d.get("type") == "link":
                st.markdown(
                    f"""
                    <div class='link-box'>
                        <h3>🕵️‍♂️ 已找到书籍详情页</h3>
                        <p><b>{d['title']}</b><br>作者: {d['author']}</p>
                        <hr style="margin:10px 0; border:0; border-top:1px solid #bbeeef;">
                        <p>请点击下方链接去浏览器手动下载：</p>
                        <a href="{d['url']}" target="_blank">👉 点击打开: {d['title']} 👈</a>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                # 额外提供一个复制框，方便复制
                st.text_input("或复制此链接:", d['url'])
                st.caption(f"来源: {res['source']} (耗时 {res['time']:.2f}s)")

            # 情况 B: 这是一个文件 (其他小说网)
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






