import io
import os
from pypdf import PdfReader, PdfWriter
import pdfplumber

reportlab_available = True
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
except ImportError:
    reportlab_available = False

import streamlit as st

st.set_page_config(page_title="PDF 頁面預覽、刪除與考卷目錄生成工具", layout="wide")

st.title("📑 PDF 頁面預覽、刪除、考卷目錄生成與標註工具")
st.markdown("上傳多個 PDF 檔案，**自動辨識考卷標題、剔除答案頁**，並產生乾淨俐落的目錄清單！")
st.markdown("---")

uploaded_files = st.file_uploader(
    "上傳 PDF 檔案（可多選）", type=["pdf"], accept_multiple_files=True
)

if uploaded_files:
    current_files_sig = "-".join([f"{f.name}_{f.size}" for f in uploaded_files])
    if "files_sig" not in st.session_state or st.session_state["files_sig"] != current_files_sig:
        st.session_state["files_sig"] = current_files_sig
        st.session_state["page_states"] = {}

    st.success(f"✅ 成功上傳 {len(uploaded_files)} 個檔案！正在分析頁面與標題...")

    all_pages_info = []
    
    for f_idx, file in enumerate(uploaded_files):
        file_bytes = file.read()
        
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            detected_title = file.name
            if len(pdf.pages) > 0:
                first_page_text = pdf.pages[0].extract_text()
                if first_page_text:
                    lines = [line.strip() for line in first_page_text.split('\n') if line.strip()]
                    if lines:
                        potential_title = lines[0]
                        for l in lines[:3]:
                            if "學年度" in l or "試題" in l or "段考" in l or "期" in l:
                                potential_title = l
                                break
                        if len(potential_title) > 3:
                            detected_title = potential_title

            for p_idx, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                clean_text = page_text.replace("\n", " ").strip()
                text_snippet = clean_text[:40] + ("..." if len(clean_text) > 40 else "")
                if not text_snippet:
                    text_snippet = "（無文字內容或圖片頁）"
                
                # 安全渲染圖片：用 try-except 保護，萬一解析失敗也不會當機
                img_bytes = b""
                try:
                    img = page.to_image(resolution=80)  # 降低解析度以提升效能並減少記憶體負擔
                    img_buffer = io.BytesIO()
                    img.original.save(img_buffer, format="PNG")
                    img_bytes = img_buffer.getvalue()
                except Exception:
                    img_bytes = b"" # 渲染失敗時保持空值，後續會自動改用文字呈現

                page_unique_id = f"f{f_idx}_p{p_idx}_{file.name}"
                
                if page_unique_id not in st.session_state["page_states"]:
                    st.session_state["page_states"][page_unique_id] = True

                all_pages_info.append({
                    "id": page_unique_id,
                    "file_name": file.name,
                    "exam_title": detected_title,
                    "file_bytes": file_bytes,
                    "page_index": p_idx,
                    "text_snippet": text_snippet,
                    "img_bytes": img_bytes,
                    "label": f"【{file.name}】第 {p_idx+1} 頁"
                })

    st.markdown("---")
    st.subheader("🖼️ 逐頁預覽與選取（請勾選要保留的頁面，取消勾選即可刪除答案頁）")

    selected_page_ids = []
    cols_per_row = 3
    for i in range(0, len(all_pages_info), cols_per_row):
        row_cols = st.columns(cols_per_row)
        for j in range(cols_per_row):
            if i + j < len(all_pages_info):
                item = all_pages_info[i + j]
                with row_cols[j]:
                    # 有成功渲染出圖片就顯示圖片，如果該頁解析失敗則改顯示提示與文字摘要
                    if item["img_bytes"]:
                        st.image(item["img_bytes"], caption=item["label"], use_container_width=True)
                    else:
                        st.warning(f"⚠️ {item['label']} 圖片無法渲染，改用文字檢視")
                    
                    st.caption(f"📝 內容預覽：{item['text_snippet']}")
                    
                    is_checked = st.checkbox(
                        "保留此頁", 
                        value=st.session_state["page_states"].get(item["id"], True),
                        key=f"cb_{item['id']}"
                    )
                    st.session_state["page_states"][item["id"]] = is_checked
                    
                    if is_checked:
                        selected_page_ids.append(item["id"])
                    st.markdown("---")

    st.subheader("⚙️ 目錄與輸出設定")
    col1, col2 = st.columns(2)
    with col1:
        add_toc_flag = st.checkbox("在最前面自動新增一頁「考卷目錄頁」", value=True)
    with col2:
        add_footer_flag = st.checkbox("在所有頁面底部加上大號頁碼", value=True)

    if st.button("🚀 確認刪除所選頁面、生成考卷目錄並組合新 PDF", type="primary"):
        if not selected_page_ids:
            st.warning("⚠️ 請至少保留一個頁面！")
        else:
            try:
                id_to_info = {item["id"]: item for item in all_pages_info}
                readers_cache = {}
                temp_writer = PdfWriter()

                selected_items = []
                for sel_id in selected_page_ids:
                    info = id_to_info[sel_id]
                    f_bytes = info["file_bytes"]
                    if f_bytes not in readers_cache:
                        readers_cache[f_bytes] = PdfReader(io.BytesIO(f_bytes))
                    
                    target_reader = readers_cache[f_bytes]
                    temp_writer.add_page(target_reader.pages[info["page_index"]])
                    selected_items.append(info)

                temp_output_stream = io.BytesIO()
                temp_writer.write(temp_output_stream)
                temp_output_stream.seek(0)
                
                base_reader = PdfReader(temp_output_stream)
                final_writer = PdfWriter()
                
                toc_page_count = 1 if add_toc_flag else 0
                total_pages = len(base_reader.pages) + toc_page_count

                exam_summary = {}
                for idx, info in enumerate(selected_items):
                    f_name = info["file_name"]
                    actual_page_num = idx + 1 + toc_page_count  
                    
                    if f_name not in exam_summary:
                        exam_summary[f_name] = {
                            "start_page": actual_page_num,
                            "exam_title": info["exam_title"]
                        }

                font_name = "Helvetica"
                if reportlab_available:
                    font_registered = False
                    try:
                        font_path = "NotoSansTC-VariableFont_wght.ttf"
                        if os.path.exists(font_path):
                            pdfmetrics.registerFont(TTFont("CustomBold", font_path))
                            font_name = "CustomBold"
                            font_registered = True
                    except Exception:
                        pass
                    
                    if not font_registered:
                        try:
                            font_path_win = "C:/Windows/Fonts/msjh.ttc"
                            if os.path.exists(font_path_win):
                                pdfmetrics.registerFont(TTFont("CustomBold", font_path_win, subfontIndex=1))
                                font_name = "CustomBold"
                                font_registered = True
                            else:
                                font_path_win_reg = "C:/Windows/Fonts/msjh.ttc"
                                pdfmetrics.registerFont(TTFont("CustomBold", font_path_win_reg, subfontIndex=0))
                                font_name = "CustomBold"
                                font_registered = True
                        except Exception:
                            font_name = "Helvetica"

                if add_toc_flag:
                    toc_packet = io.BytesIO()
                    sample_page = base_reader.pages[0]
                    width = float(sample_page.mediabox.width)
                    height = float(sample_page.mediabox.height)
                    
                    toc_can = canvas.Canvas(toc_packet, pagesize=(width, height))
                    toc_can.saveState()
                    
                    toc_can.setFont(font_name, 24)
                    toc_can.setFillColorRGB(0.05, 0.15, 0.35)
                    toc_can.drawCentredString(width / 2, height - 60, "【 考 卷 目 錄 清 單 】")
                    
                    toc_can.setStrokeColorRGB(0.2, 0.4, 0.7)
                    toc_can.setLineWidth(1.5)
                    toc_can.line(50, height - 75, width - 50, height - 75)
                    
                    toc_can.setFont(font_name, 13)
                    toc_can.setFillColorRGB(0.1, 0.1, 0.1)
                    
                    start_y = height - 120
                    line_height = 36
                    
                    for idx, (f_name, data) in enumerate(exam_summary.items()):
                        if start_y < 60:
                            break
                        
                        exam_title = f"{idx + 1}. {data['exam_title']}"
                        page_info_str = f"第 {data['start_page']} 頁"
                        
                        if len(exam_title) > 42:
                            exam_title = exam_title[:40] + "..."

                        toc_can.drawString(50, start_y, exam_title)
                        toc_can.drawRightString(width - 50, start_y, page_info_str)
                        
                        toc_can.setStrokeColorRGB(0.8, 0.8, 0.8)
                        toc_can.setLineWidth(0.5)
                        toc_can.line(50, start_y - 6, width - 50, start_y - 6)
                        
                        start_y -= line_height

                    if add_footer_flag:
                        toc_can.setFont(font_name, 14)
                        toc_can.setFillColorRGB(0.1, 0.1, 0.1)
                        toc_can.drawCentredString(width / 2, 30, f"第 1 頁 / 共 {total_pages} 頁")
                        
                    toc_can.restoreState()
                    toc_can.save()
                    toc_packet.seek(0)
                    toc_page_reader = PdfReader(toc_packet)
                    final_writer.add_page(toc_page_reader.pages[0])

                for idx, page in enumerate(base_reader.pages):
                    packet = io.BytesIO()
                    width = float(page.mediabox.width)
                    height = float(page.mediabox.height)
                    can = canvas.Canvas(packet, pagesize=(width, height))
                    current_final_page_num = idx + (2 if add_toc_flag else 1)
                    
                    if add_footer_flag:
                        can.saveState()
                        mask_width = 180
                        mask_height = 35
                        mask_x = (width - mask_width) / 2
                        mask_y = 12
                        can.setFillColorRGB(1, 1, 1)
                        can.setStrokeColorRGB(1, 1, 1)
                        can.rect(mask_x, mask_y, mask_width, mask_height, fill=1, stroke=1)
                        can.setFont(font_name, 16)
                        can.setFillColorRGB(0.1, 0.1, 0.1)
                        page_str = f"第 {current_final_page_num} 頁 / 共 {total_pages} 頁"
                        can.drawCentredString(width / 2, 20, page_str)
                        can.restoreState()
                        
                    can.save()
                    packet.seek(0)
                    overlay_reader = PdfReader(packet)
                    page.merge_page(overlay_reader.pages[0])
                    final_writer.add_page(page)

                final_output = io.BytesIO()
                final_writer.write(final_output)
                final_output.seek(0)
                
                st.success("🎉 PDF 處理完畢，已成功產生成品！")
                st.download_button(
                    label="💾 下載全新整理好的 PDF 檔案",
                    data=final_output,
                    file_name="HS_Exam_Review_Clean.pdf",
                    mime="application/pdf",
                )
            except Exception as e:
                st.error(f"❌ 處理失敗：{e}")