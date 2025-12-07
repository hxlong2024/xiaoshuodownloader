import streamlit as st
import requests
from bs4 import BeautifulSoup
import os
import re
import zipfile


# ==========================================
# 1. 核心爬虫逻辑 (直接复用，完全不用改)
# ==========================================
class JJJXSW_Engine:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Mobile Safari/537.36",
            "Referer": "https://m.jjjxsw.com/"
        }
        self.base_url = "https://m.jjjxsw.com"

    def run(self, keyword):
        """
        返回: (文件名, 文件二进制内容) 或者 (None, None)
        """
        log_msgs = []

        def log(msg):
            log_msgs.append(msg)

        try:
            # 1. 搜索
            log("🔍 [1/4] 正在搜索...")
            search_url = f"{self.base_url}/e/search/index.php"
            data = {"keyboard": keyword, "Submit22": "搜索", "show": "title"}
            resp = requests.post(search_url, data=data, headers=self.headers)
            resp.encoding = 'utf-8'
            soup = BeautifulSoup(resp.text, 'html.parser')

            result_items = soup.select(".booklist_a .list_a .main")
            if not result_items:
                return None, None, log_msgs + ["❌ 搜索无结果"]

            main_div = result_items[0]
            link_tag = main_div.find('a')
            raw_title = link_tag.get_text().strip()
            intro_href = link_tag['href']

            # 提取作者
            author = "佚名"
            for span in main_div.find_all('span'):
                if "作者" in span.get_text():
                    author = span.get_text().replace("作者：", "").replace("作者:", "").strip()
                    break
            log(f"📖 锁定: 《{raw_title}》 作者: {author}")

            # 2. 介绍页
            intro_url = self.base_url + intro_href
            headers_intro = self.headers.copy()
            headers_intro['Referer'] = search_url
            intro_resp = requests.get(intro_url, headers=headers_intro)
            intro_resp.encoding = 'utf-8'
            intro_soup = BeautifulSoup(intro_resp.text, 'html.parser')

            # 3. 寻找确认页
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

            if not confirm_url: return None, None, log_msgs + ["❌ 未找到下载入口"]
            if not confirm_url.startswith("http"): confirm_url = self.base_url + confirm_url

            # 4. 解析真实地址
            headers_confirm = self.headers.copy()
            headers_confirm['Referer'] = intro_url
            confirm_resp = requests.get(confirm_url, headers=headers_confirm)
            confirm_soup = BeautifulSoup(confirm_resp.text, 'html.parser')

            target_link = confirm_soup.find('a', id='id0')
            if not target_link:
                target_link = confirm_soup.find('a', href=re.compile(r'doaction\.php'))

            if not target_link: return None, None, log_msgs + ["❌ 无法解析 doaction 链接"]

            real_url = target_link['href']
            if not real_url.startswith("http"): real_url = self.base_url + real_url

            # 5. 下载内容到内存
            log("⬇️ [4/4] 正在下载文件流...")
            headers_file = self.headers.copy()
            headers_file['Referer'] = confirm_url

            file_resp = requests.get(real_url, headers=headers_file)  # 不使用stream，直接读入内存

            if file_resp.status_code == 200:
                clean_title = re.sub(r'[\\/*?:"<>|]', "", raw_title)
                clean_author = re.sub(r'[\\/*?:"<>|]', "", author)
                filename = f"{clean_title} by {clean_author}.txt"
                log("✅ 下载成功！")
                return filename, file_resp.content, log_msgs
            else:
                return None, None, log_msgs + [f"❌ HTTP错误: {file_resp.status_code}"]

        except Exception as e:
            return None, None, log_msgs + [f"❌ 异常: {e}"]


# ==========================================
# 2. Streamlit 网页界面
# ==========================================

st.set_page_config(page_title="小说下载器", page_icon="📚")

st.title("📚 手机小说下载助手")
st.write("在手机上输入书名，电脑帮你跑腿下载。")

# 输入框
keyword = st.text_input("输入小说名称", placeholder="例如：恒星时刻")

# 按钮
if st.button("开始搜索并下载", type="primary"):
    if not keyword:
        st.warning("请输入名称！")
    else:
        engine = JJJXSW_Engine()

        # 显示进度条
        with st.spinner('正在电脑后台疯狂运行中...'):
            filename, file_content, logs = engine.run(keyword)

        # 显示日志
        with st.expander("查看运行日志"):
            for msg in logs:
                st.write(msg)

        # 结果处理
        if filename and file_content:
            st.success(f"成功找到：{filename}")

            # --- 核心功能：提供给手机下载 ---
            # 1. 下载 TXT
            st.download_button(
                label="📥 点击下载 TXT 到手机",
                data=file_content,
                file_name=filename,
                mime="text/plain"
            )

            # 2. 压缩并下载 ZIP
            # 在内存中创建ZIP
            import io

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                zip_file.writestr(filename, file_content)

            st.download_button(
                label="📦 点击下载 ZIP 到手机",
                data=zip_buffer.getvalue(),
                file_name=filename.replace(".txt", ".zip"),
                mime="application/zip"
            )
        else:
            st.error("下载失败，请查看上方日志。")