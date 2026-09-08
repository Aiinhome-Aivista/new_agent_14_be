import os
import io
import PyPDF2
import docx
import pandas as pd
import logging

logger = logging.getLogger(__name__)

class DocTool:
    """
    Tool for parsing uploaded MOMs/reports/budget files (docx, pdf, xlsx).
    """
    @staticmethod
    def parse_file(file_path: str) -> str:
        """
        Reads a file from the given path and extracts text.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        
        try:
            if ext == '.pdf':
                return DocTool._parse_pdf(file_path)
            elif ext == '.docx':
                return DocTool._parse_docx(file_path)
            elif ext in ['.xlsx', '.xls']:
                return DocTool._parse_excel(file_path)
            elif ext in ['.txt', '.md', '.csv']:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                raise ValueError(f"Unsupported file format: {ext}")
        except Exception as e:
            logger.error(f"Error parsing file {file_path}: {e}")
            raise

    @staticmethod
    def _parse_pdf(file_path: str) -> str:
        text = ""
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text

    @staticmethod
    def _parse_docx(file_path: str) -> str:
        doc = docx.Document(file_path)
        return "\n".join([para.text for para in doc.paragraphs])

    @staticmethod
    def _parse_excel(file_path: str) -> str:
        # Read all sheets, concatenate to CSV string
        df_dict = pd.read_excel(file_path, sheet_name=None)
        text = ""
        for sheet_name, df in df_dict.items():
            text += f"\n--- Sheet: {sheet_name} ---\n"
            text += df.to_csv(index=False)
        return text
