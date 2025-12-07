import streamlit as st
import aiohttp
import asyncio
from bs4 import BeautifulSoup
import re
import zipfile
import io
import time
import urllib.parse


# ==========================================
# 1. 基础引擎架构 (升级版：带书名核对)
# ==========================================

class BaseEngine:
    def __init__(self):
        self.source_name = "未知源"
        self.base_url = ""
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Mobile Safari/537.36"
        }

    def log(self, msgs, text):
        msgs.append(f"[{self.source_name}] {text}")

    def clean_filename(self, text):
        return re.sub(r'[\\/*?:"<>|]', "", text).strip()

    def validate_title(self, user_keyword, site_title):
        """
        书名核对逻辑：
        1. 去除标点符号和空格
        2. 确保 用户输入的关键词 包含在 网站标题 中
        """

        # 只保留汉字、字母、数字
        def clean(s):
            return re.sub(r'[^\w\u4e00-\u9fa5]', '', s).lower()

        kw = clean(user_keyword)
        st = clean(site_title)

        # 核心逻辑：网站标题必须包含用户搜的词 (或者完全相等)
        # 比如搜 "元尊"，结果 "元尊(精校版)" -> 通过
        # 比如搜 "元尊"，结果 "斗破苍穹" -> 失败
        is_match = kw in st
        return is_match

    async def run(self, session, keyword):
        raise NotImplementedError


# ==========================================
# 2. 99小说网 引擎 (带校验)
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
            search_url = f"{self.base_url}/e/search/index.php"
            data = {"keyboard": keyword, "Submit22": "搜索", "show": "title"}

            async with session.post(search_url, data=data, headers=self.headers) as resp:
                text = await resp.text(encoding='utf-8', errors='ignore')
                soup = BeautifulSoup(text, 'html.parser')

            result_items = soup.select(".booklist_a .list_a .main")

            target_item = None
            target_title = ""
            target_href = ""
            target_author = "佚名"

            # === 循环检查所有结果 ===
            for item in result_items:
                link_tag = item.find('a')
                if not link_tag: continue

                raw_title = link_tag.get_text().strip()

                # 核对书名
                if self.validate_title(keyword, raw_title):
                    target_item = item
                    target_title = raw_title
                    target_href = link_tag['href']

                    # 提取作者
                    for span in item.find_all('span'):
                        if "作者" in span.get_text():
                            target_author = span.get_text().replace("作者：", "").replace("作者:", "").strip()
                            break
                    break  # 找到匹配的就跳出
                else:
                    self.log(logs, f"⚠️ 跳过不匹配结果: {raw_title}")

            if not target_item:
                self.log(logs, "❌ 未找到匹配书名的结果")
                return False, None, logs

            self.log(logs, f"✅ 匹配成功: 《{target_title}》")

            # Step 2: 介绍页
            intro_url = self.base_url + target_href
            async with session.get(intro_url, headers=self.headers) as resp:
                intro_soup = BeautifulSoup(await resp.text(encoding='utf-8', errors='ignore'), 'html.parser')

            confirm_url = None
            sso_area = intro_soup.select_one(".sso_d")
            if sso_area:
                for link in sso_area.find_all('a'):
                    if "下载" in link.get_text() or "txt" in link.get_text().lower():
                        confirm_url = link.get('href')
                        break
            if not confirm_url:
                t = intro_soup.find('a', string=re.compile("下载"))
                if t: confirm_url = t['href']

            if not confirm_url: return False, None, logs
            if not confirm_url.startswith("http"): confirm_url = self.base_url + confirm_url

            # Step 3: 解析真实链接
            async with session.get(confirm_url, headers=self.headers) as resp:
                confirm_soup = BeautifulSoup(await resp.text(encoding='utf-8', errors='ignore'), 'html.parser')

            target_link = confirm_soup.find('a', id='id0') or confirm_soup.find('a', href=re.compile(r'doaction\.php'))
            if not target_link: return False, None, logs

            real_url = target_link['href']
            if not real_url.startswith("http"): real_url = self.base_url + real_url

            # Step 4: 下载
            self.log(logs, "⬇️ 拉取文件流...")
            async with session.get(real_url, headers=self.headers) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    filename = f"{self.clean_filename(target_title)} by {self.clean_filename(target_author)}.txt"
                    return True, {"filename": filename, "author": target_author, "content": content}, logs

            return False, None, logs
        except Exception as e:
            self.log(logs, f"❌ 异常: {e}")
            return False, None, logs


# ==========================================
# 3. 00小说网 引擎 (带校验)
# ==========================================

class ZeroShu_Engine(BaseEngine):
    def __init__(self):
        super().__init__()
        self.source_name = "00小说网"
        self.base_url = "https://m.00shu.la"

    async def run(self, session, keyword):
        logs = []
        try:
            self.log(logs, f"🚀 搜索: {keyword}")
            search_url = f"{self.base_url}"
            data = {"searchkey": keyword, "type": "articlename"}

            async with session.post(search_url, data=data, headers=self.headers) as resp:
                soup = BeautifulSoup(await resp.text(errors='ignore'), 'html.parser')

            results = soup.select(".searchresult .sone")

            target_title = ""
            target_href = ""
            target_author = "佚名"
            found_match = False

            # === 循环检查所有结果 ===
            for item in results:
                a_tag = item.find('a')
                if not a_tag: continue

                raw_title = a_tag.get_text().strip()

                # 核对书名
                if self.validate_title(keyword, raw_title):
                    target_title = raw_title
                    target_href = a_tag['href']

                    span_auth = item.find('span', class_='author')
                    if span_auth:
                        target_author = span_auth.get_text().strip()

                    found_match = True
                    break  # 找到就停
                else:
                    self.log(logs, f"⚠️ 跳过不匹配结果: {raw_title}")

            if not found_match:
                self.log(logs, "❌ 无匹配书名的结果")
                return False, None, logs

            self.log(logs, f"✅ 匹配成功: 《{target_title}》")

            detail_url = target_href if target_href.startswith("http") else self.base_url + target_href

            # Step 2: 详情页
            async with session.get(detail_url, headers=self.headers) as resp:
                detail_soup = BeautifulSoup(await resp.text(errors='ignore'), 'html.parser')

            btn_list = detail_soup.find(id="btnlist")
            intermediate_href = None
            if btn_list:
                link_tag = btn_list.find('a', string=re.compile("下载"))
                if link_tag: intermediate_href = link_tag['href']

            if not intermediate_href: return False, None, logs
            intermediate_url = intermediate_href if intermediate_href.startswith(
                "http") else self.base_url + intermediate_href

            # Step 3: 解析真实文件
            async with session.get(intermediate_url, headers=self.headers) as resp:
                down_soup = BeautifulSoup(await resp.text(errors='ignore'), 'html.parser')

            file_link = down_soup.find('a', href=re.compile(r'\.(txt|zip|rar)$', re.IGNORECASE))
            if not file_link:
                file_link = down_soup.find('a', string=re.compile("下载"),
                                           href=lambda h: h and ('txt' in h or 'down' in h))

            if not file_link: return False, None, logs
            real_file_url = file_link['href']
            if not real_file_url.startswith("http"): real_file_url = urllib.parse.urljoin(intermediate_url,
                                                                                          real_file_url)

            # Step 4: 下载
            self.log(logs, "⬇️ 拉取文件流...")
            async with session.get(real_file_url, headers=self.headers) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    ext = ".txt"
                    if content[:2] == b'PK':
                        ext = ".zip"
                    elif content[:2] == b'Rar':
                        ext = ".rar"

                    filename = f"{self.clean_filename(target_title)} by {self.clean_filename(target_author)}{ext}"
                    return True, {"filename": filename, "author": target_author, "content": content}, logs

            return False, None, logs
        except Exception as e:
            self.log(logs, f"❌ 异常: {e}")
            return False, None, logs


# ==========================================
# 4. 赛马调度 (逻辑不变)
# ==========================================

async def search_race_mode(keyword):
    engine_classes = [JJJXSW_Engine, ZeroShu_Engine]
    start_time = time.time()
    all_logs = []

    async with aiohttp.ClientSession() as session:
        tasks = []
        for EngineCls in engine_classes:
            engine = EngineCls()
            task = asyncio.create_task(engine.run(session, keyword))
            task.set_name(engine.source_name)
            tasks.append(task)

        pending = set(tasks)
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                success, result, logs = await task
                all_logs.extend(logs)
                if success and result:
                    winner_source = task.get_name()
                    for p_task in pending: p_task.cancel()  # 熔断其他
                    return {"success": True, "source": winner_source, "data": result, "logs": all_logs,
                            "time": time.time() - start_time}

    return {"success": False, "logs": all_logs, "time": time.time() - start_time}


# ==========================================
# 5. Streamlit 界面
# ==========================================
st.set_page_config(page_title="严谨版赛马下载器", page_icon="🐴", layout="centered")
st.markdown(
    """<style>.stButton>button { width: 100%; border-radius: 8px; font-weight: bold; } .success-box { padding: 15px; background: #e6fffa; border: 1px solid #38b2ac; color: #234e52; border-radius: 8px; margin-bottom: 15px;}</style>""",
    unsafe_allow_html=True)

st.title("🐴 极速且严谨的小说下载")
st.caption("并发赛马 + 智能书名校验 | 杜绝假资源")

keyword = st.text_input("输入书名", placeholder="例如：元尊")

if st.button("🚀 极速搜索", type="primary"):
    if not keyword:
        st.warning("请输入书名！")
    else:
        status_text = st.empty()
        status_text.info("🔎 正在并发检索并核对书名...")

        result = asyncio.run(search_race_mode(keyword))
        status_text.empty()

        if result["success"]:
            data = result['data']
            st.markdown(f"""
            <div class="success-box">
                <h3>✅ 校验通过！</h3>
                <b>书名：</b>{data['filename']}<br>
                <b>来源：</b>{result['source']} (耗时 {result['time']:.2f}s)
            </div>
            """, unsafe_allow_html=True)

            col1, col2 = st.columns(2)
            with col1:
                st.download_button("📥 下载文件", data['content'], file_name=data['filename'])
            with col2:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zf:
                    zf.writestr(data['filename'], data['content'])
                st.download_button("📦 下载 ZIP", zip_buffer.getvalue(), file_name=data['filename'] + ".zip",
                                   mime="application/zip")
        else:
            st.error("😭 未找到匹配该书名的资源 (已自动过滤不相关结果)")

        with st.expander("📊 查看校验日志"):

            for msg in result["logs"]: st.text(msg)
