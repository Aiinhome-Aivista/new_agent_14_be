import os
import re

def clean_numeric_str(val_str):
    if val_str is None:
        return 0.0
    s = str(val_str).strip()
    if not s:
        return 0.0
    # Strip parenthetical annotations e.g. "$1,650,000 (66%)" -> "$1,650,000"
    s = re.sub(r'\(.*?\)', '', s).strip()
    # Handle currency symbols, percentages, and multipliers
    s_clean = s.replace('$', '').replace('€', '').replace('£', '').replace('₹', '').replace(',', '').strip()
    multiplier = 1.0
    if s_clean.lower().endswith('m'):
        multiplier = 1000000.0
        s_clean = s_clean[:-1].strip()
    elif s_clean.lower().endswith('k'):
        multiplier = 1000.0
        s_clean = s_clean[:-1].strip()
    elif s_clean.endswith('%'):
        s_clean = s_clean[:-1].strip()

    num_part = re.sub(r'[^\d.-]', '', s_clean)
    try:
        return float(num_part) * multiplier
    except Exception:
        return 0.0


def extract_raw_tables_and_text(file_path):
    """
    Extracts tabular data and text paragraphs from any supported document format:
    - DOCX (.docx) via python-docx
    - XLSX / XLS (.xlsx, .xls) via openpyxl
    - CSV (.csv) via standard csv module
    - PDF (.pdf) via PyMuPDF (fitz) with native table detection
    - TXT / JSON (.txt, .json)
    Returns: (list_of_tables, list_of_paragraphs)
    where each table is a 2D list of cleaned string cells: [[c0, c1, ...], ...]
    """
    if not file_path or not os.path.exists(file_path):
        return [], []

    ext = os.path.splitext(file_path)[1].lower()
    tables = []
    paragraphs = []

    # 1. DOCX
    if ext == '.docx':
        try:
            from docx import Document
            doc = Document(file_path)
            for p in doc.paragraphs:
                txt = p.text.strip()
                if txt:
                    paragraphs.append(txt)
            for t in doc.tables:
                t_data = []
                for row in t.rows:
                    r_cells = [cell.text.strip() for cell in row.cells]
                    if any(r_cells):
                        t_data.append(r_cells)
                if t_data:
                    tables.append(t_data)
        except Exception as e:
            print(f"[DocumentParser] Error reading docx {file_path}: {e}")

    # 2. XLSX / XLS
    elif ext in ('.xlsx', '.xls'):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(file_path, data_only=True)
            for sheetname in wb.sheetnames:
                ws = wb[sheetname]
                t_data = []
                for row in ws.iter_rows(values_only=True):
                    r_cells = [str(c).strip() if c is not None else "" for c in row]
                    if any(r_cells):
                        t_data.append(r_cells)
                if t_data:
                    tables.append(t_data)
                    paragraphs.append(f"Worksheet: {sheetname}")
        except Exception as e:
            print(f"[DocumentParser] Error reading excel {file_path}: {e}")

    # 3. CSV
    elif ext == '.csv':
        try:
            import csv
            with open(file_path, mode='r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f)
                t_data = []
                for row in reader:
                    r_cells = [c.strip() for c in row]
                    if any(r_cells):
                        t_data.append(r_cells)
                if t_data:
                    tables.append(t_data)
        except Exception as e:
            print(f"[DocumentParser] Error reading csv {file_path}: {e}")

    # 4. PDF
    elif ext == '.pdf':
        try:
            import pymupdf
            doc = pymupdf.open(file_path)
            for page in doc:
                txt = page.get_text()
                if txt:
                    for line in txt.splitlines():
                        if line.strip():
                            paragraphs.append(line.strip())
                try:
                    tabs = page.find_tables()
                    for tab in tabs:
                        extracted = tab.extract()
                        if extracted:
                            t_data = []
                            for row in extracted:
                                r_cells = [str(c).strip() if c is not None else "" for c in row]
                                if any(r_cells):
                                    t_data.append(r_cells)
                            if t_data:
                                tables.append(t_data)
                except Exception:
                    pass
        except Exception as e:
            print(f"[DocumentParser] Error reading pdf {file_path}: {e}")

    # 5. TXT / JSON
    elif ext in ('.txt', '.json', '.md'):
        try:
            with open(file_path, mode='r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if line.strip():
                        paragraphs.append(line.strip())
        except Exception as e:
            print(f"[DocumentParser] Error reading text {file_path}: {e}")

    # 6. Pipe-delimited structured text table detection from paragraphs (e.g. Markdown or plain-text tables)
    pipe_tables = []
    current_pipe_table = []
    for p in paragraphs:
        line = p.strip()
        if '|' in line:
            cells = [c.strip() for c in line.split('|')]
            if len(cells) >= 2 and any(cells):
                current_pipe_table.append(cells)
            else:
                if len(current_pipe_table) >= 2:
                    pipe_tables.append(current_pipe_table)
                current_pipe_table = []
        else:
            if len(current_pipe_table) >= 2:
                pipe_tables.append(current_pipe_table)
            current_pipe_table = []
    if len(current_pipe_table) >= 2:
        pipe_tables.append(current_pipe_table)

    if pipe_tables:
        tables.extend(pipe_tables)

    return tables, paragraphs



def extract_budget_telemetry_from_tables(tables, paragraphs=None):
    """
    Parses budget categories, line items, milestones, and totals from any extracted tables.
    Works for DOCX, XLSX, XLS, CSV, and PDF tables.
    Returns: {
        'categories_raw': [...],
        'line_items_raw': [...],
        'milestones_raw': [...],
        'steerco_forecasts': {...},
        'totals': {'planned': float, 'actual': float, 'variance': float}
    }
    """
    categories_raw = []
    line_items_raw = []
    milestones_raw = []
    steerco_forecasts = {}
    totals = {'planned': 0.0, 'actual': 0.0, 'variance': 0.0}

    for t_idx, t in enumerate(tables):
        if not t or len(t) < 2:
            continue
        h = [str(c).strip().lower() for c in t[0]]

        # 1. Budget Ledger & Cost Area Table (e.g. ['Cat ID', 'Cost Area', 'Budgeted', 'Actual Spend', 'Remaining', 'Percent Used'])
        has_budget_header = any(k in x for k in ['budgeted', 'approved', 'planned', 'allocation', 'tranche amount'] for x in h) or any('budget' in x for x in h)
        has_spend_or_rem = any(k in x for k in ['actual', 'spent', 'remaining', 'percent', 'forecast', 'variance', 'balance'] for x in h)
        if has_budget_header and has_spend_or_rem:
            cat_col = next((i for i, x in enumerate(h) if any(k in x for k in ['cost area', 'category', 'area', 'description', 'domain', 'workstream'])), -1)
            if cat_col == -1:
                cat_col = next((i for i, x in enumerate(h) if any(k in x for k in ['cat id', 'id', 'code'])), 0)
            
            pl_col = next((i for i, x in enumerate(h) if any(k in x for k in ['budgeted', 'approved', 'planned', 'budget', 'allocation', 'target', 'amount'])), -1)
            ac_col = next((i for i, x in enumerate(h) if any(k in x for k in ['actual spend', 'actual', 'spent', 'incurred', 'forecast'])), -1)
            rem_col = next((i for i, x in enumerate(h) if any(k in x for k in ['remaining', 'balance', 'variance'])), -1)
            pct_col = next((i for i, x in enumerate(h) if any(k in x for k in ['percent', 'used', 'utilization', '%', 'burned'])), -1)

            for r in t[1:]:
                cells = [str(cell).strip() for cell in r]
                if not any(cells):
                    continue
                row_label = ' '.join(cells[:2]).lower()
                is_total_row = any(w in row_label for w in ['total', 'subtotal', 'overall', 'grand total'])
                
                c_pl = clean_numeric_str(cells[pl_col]) if pl_col >= 0 and len(cells) > pl_col else 0.0
                c_ac = clean_numeric_str(cells[ac_col]) if ac_col >= 0 and len(cells) > ac_col else 0.0
                c_rem = clean_numeric_str(cells[rem_col]) if rem_col >= 0 and len(cells) > rem_col else (c_pl - c_ac)
                c_pct = clean_numeric_str(cells[pct_col]) if pct_col >= 0 and len(cells) > pct_col else (round((c_ac / c_pl * 100), 1) if c_pl > 0 else 0.0)

                if is_total_row:
                    if c_pl > 0 or c_ac > 0:
                        totals['planned'] = c_pl
                        totals['actual'] = c_ac
                        totals['variance'] = c_pl - c_ac
                else:
                    c_name = cells[cat_col] if cat_col >= 0 and len(cells) > cat_col else cells[0]
                    if c_name and (c_pl > 0 or c_ac > 0) and not any(k in c_name.lower() for k in ['total', 'subtotal']):
                        categories_raw.append({
                            'name': c_name,
                            'planned': c_pl,
                            'actual': c_ac,
                            'remaining': c_rem,
                            'share_pct': c_pct,
                            'percent_used': c_pct
                        })

        # 2. Key-Value / Metrics Table Format (e.g. ['Metric', 'Value'] or ['Field', 'Target'])
        if any(k in h for k in ['metric', 'kpi', 'field', 'indicator']) and any(k in h for k in ['value', 'amount', 'target', 'actual', 'status']):
            k_idx = next((i for i, x in enumerate(h) if any(k in x for k in ['metric', 'kpi', 'field', 'indicator'])), 0)
            v_idx = next((i for i, x in enumerate(h) if any(k in x for k in ['value', 'amount', 'target', 'actual'])), 1)
            for r in t[1:]:
                cells = [str(cell).strip() for cell in r]
                if len(cells) > max(k_idx, v_idx):
                    k_str = cells[k_idx].lower()
                    if any(term in k_str for term in ['budget spent', 'actual spend', 'total spend', 'spend', 'burned']) and totals.get('actual', 0.0) == 0.0:
                        v_num = clean_numeric_str(cells[v_idx])
                        if v_num > 0:
                            totals['actual'] = v_num
                    elif any(term in k_str for term in ['total budget', 'budgeted', 'approved budget', 'planned spend', 'total capital']) and totals.get('planned', 0.0) == 0.0:
                        v_num = clean_numeric_str(cells[v_idx])
                        if v_num > 0:
                            totals['planned'] = v_num

        # 3. SteerCo/MOM cost forecast tables
        if any('cost area' in x or 'area' in x for x in h) and any('forecast' in x for x in h):
            for r in t[1:]:
                c = [str(cell).strip() for cell in r]
                if len(c) >= 3 and 'total' not in c[0].lower():
                    steerco_forecasts[c[0].lower()] = {
                        'area': c[0],
                        'approved': clean_numeric_str(c[1]),
                        'forecast': clean_numeric_str(c[2]),
                        'variance': clean_numeric_str(c[3]) if len(c) > 3 else 0.0
                    }

        # 3. Category Summary Table (Category, Cost, % of Total)
        if any('category' in x for x in h) and any('cost' in x or 'amount' in x for x in h) and not any('monthly' in x for x in h) and not categories_raw:
            cost_col = -1
            pct_col = -1
            for idx_c, col_name in enumerate(h):
                if any(p in col_name for p in ['%', 'share', 'percent', 'pct']):
                    pct_col = idx_c
                elif any(k in col_name for k in ['cost', 'amount', 'budget', 'planned', 'total', 'price', 'val']):
                    cost_col = idx_c
            if cost_col == -1 and len(h) > 1:
                cost_col = 1
            if cost_col != -1:
                for r in t[1:]:
                    cells = [str(cell).strip() for cell in r]
                    if not cells or 'total' in cells[0].lower():
                        continue
                    cat_name = cells[0]
                    c_pl = clean_numeric_str(cells[cost_col]) if len(cells) > cost_col else 0.0
                    c_pct = clean_numeric_str(cells[pct_col]) if pct_col >= 0 and len(cells) > pct_col else 0.0
                    if cat_name and c_pl > 0:
                        categories_raw.append({
                            'name': cat_name,
                            'planned': c_pl,
                            'actual': 0.0,
                            'remaining': c_pl,
                            'share_pct': c_pct
                        })

        # 4. Line item tables
        has_cost = any(any(k in x for k in ['cost', 'amount', 'total', 'rate', 'budget']) for x in h)
        first_header = h[0] if h else ''
        is_line_item_table = has_cost and any(k in first_header for k in ['role', 'item', 'integration', 'activity', 'resource', 'service', 'task'])

        cat_col_idx = next((i for i, col in enumerate(h) if any(k in col for k in ['category', 'domain', 'cost center'])), -1)
        item_col_idx = next((i for i, col in enumerate(h) if any(k in col for k in ['item', 'title', 'deliverable', 'description', 'role', 'name'])), -1)
        cost_col_idx = next((i for i, col in enumerate(h) if any(k in col for k in ['total', 'cost', 'amount', 'budget', 'rate'])), -1)

        if is_line_item_table and cat_col_idx == -1:
            if 'role' in first_header or 'resource' in first_header:
                parent_cat = 'A. Human Resources (Development)'
            elif 'integration' in first_header or 'connector' in first_header:
                parent_cat = 'D. Data Integration & Connectors'
            elif any('test' in str(c).lower() for c in t[1][:2]) or 'qa' in first_header:
                parent_cat = 'E. Testing & QA'
            elif 'item' in first_header:
                row_texts = " ".join(" ".join(str(cell) for cell in r) for r in t[1:4]).lower()
                if any(w in row_texts for w in ['aws', 'azure', 'gcp', 'cloud', 'server', 'database', 'compute', 'storage', 'rds']):
                    parent_cat = 'B. Infrastructure & Hosting'
                else:
                    parent_cat = 'C. Tools, Licenses & Platforms'
            elif 'activity' in first_header:
                row_texts = " ".join(" ".join(str(cell) for cell in r) for r in t[1:4]).lower()
                if 'pmo' in row_texts or 'governance' in row_texts or 'management' in row_texts:
                    parent_cat = 'F. Project Management & Governance'
                else:
                    parent_cat = 'E. Testing & QA'
            else:
                parent_cat = 'F. Project Management & Governance'

            cost_col = -1
            for idx_c, col_name in enumerate(h):
                if any(k in col_name for k in ['total', 'total cost', 'cost', 'estimated cost', 'amount']):
                    cost_col = idx_c

            for r in t[1:]:
                cells = [str(cell).strip() for cell in r]
                if not cells or any(k in cells[0].lower() for k in ['subtotal', 'total']):
                    continue
                details_str = ' • '.join([f'{h[ci].title()}: {cells[ci]}' for ci in range(1, len(cells)) if len(cells) > ci and cells[ci] and ci != cost_col])
                line_items_raw.append({
                    'title': cells[0],
                    'category': parent_cat,
                    'planned': clean_numeric_str(cells[cost_col]) if cost_col >= 0 and len(cells) > cost_col else 0.0,
                    'details': details_str
                })
        elif cat_col_idx != -1 and item_col_idx != -1 and cost_col_idx != -1 and cat_col_idx != item_col_idx:
            for r in t[1:]:
                cells = [str(cell).strip() for cell in r]
                if not cells or any(k in cells[item_col_idx].lower() for k in ['subtotal', 'total']):
                    continue
                item_title = cells[item_col_idx] if len(cells) > item_col_idx else ""
                item_cat = cells[cat_col_idx] if len(cells) > cat_col_idx else "General Project Costs"
                item_cost = clean_numeric_str(cells[cost_col_idx]) if len(cells) > cost_col_idx else 0.0
                if item_title and item_cost > 0:
                    details_str = ' • '.join([f'{h[ci].title()}: {cells[ci]}' for ci in range(len(cells)) if len(cells) > ci and cells[ci] and ci not in (item_col_idx, cost_col_idx)])
                    line_items_raw.append({
                        'title': item_title,
                        'category': item_cat,
                        'planned': item_cost,
                        'details': details_str
                    })

        # 5. Milestone Payment Tranches Table
        is_milestone_table = (
            any('milestone' in x for x in h) or 
            any('tranche' in x for x in h) or 
            ('deliverable' in h and any(k in h for k in ['amount', 'tranche', 'due date', 'criteria', 'id']))
        )
        if is_milestone_table and any(any(k in col for k in ['% payment', '%', 'amount', 'deliverable', 'tranche', 'value', 'price', 'cost']) for col in h) and not milestones_raw:
            amt_col = -1
            pct_col = -1
            deliv_col = 1 if len(h) > 1 else 0
            m_code_col = 0
            for idx_c, col_name in enumerate(h):
                if any(k in col_name for k in ['amount', 'cost', 'value', 'price', 'tranche']):
                    amt_col = idx_c
                elif any(k in col_name for k in ['%', 'payment', 'pct', 'share']):
                    pct_col = idx_c
                elif any(k in col_name for k in ['deliverable', 'description', 'name']):
                    deliv_col = idx_c
                elif any(k in col_name for k in ['milestone', 'code']) or col_name == 'id':
                    m_code_col = idx_c

            for r in t[1:]:
                cells = [str(cell).strip() for cell in r]
                if not cells or 'total' in cells[0].lower():
                    continue
                m_code = cells[m_code_col] if len(cells) > m_code_col else ''
                deliv = cells[deliv_col] if len(cells) > deliv_col and deliv_col != m_code_col else ''
                if m_code:
                    milestones_raw.append({
                        'id': m_code,
                        'name': f'{m_code}: {deliv}' if deliv else m_code,
                        'percentage': clean_numeric_str(cells[pct_col]) if pct_col >= 0 and len(cells) > pct_col else 0.0,
                        'amount': clean_numeric_str(cells[amt_col]) if amt_col >= 0 and len(cells) > amt_col else 0.0
                    })

    # Contingency buffer line item
    cont_cat = next((c for c in categories_raw if 'contingency' in c['name'].lower()), None)
    if cont_cat and not any('contingency' in x['title'].lower() for x in line_items_raw):
        line_items_raw.append({
            'title': 'Project Contingency Reserve Buffer',
            'category': cont_cat['name'],
            'planned': cont_cat['planned'],
            'details': 'Contractual contingency buffer for scope change and technical risk'
        })

    # Fallback / Rollup totals calculation if table had no TOTAL row
    if totals.get('planned', 0.0) == 0.0 and categories_raw:
        totals['planned'] = sum(c['planned'] for c in categories_raw)
        totals['actual'] = sum(c.get('actual', 0.0) for c in categories_raw)
        totals['variance'] = totals['planned'] - totals['actual']

    # Fallback to paragraph extraction if totals still zero
    if paragraphs:
        for p in paragraphs:
            if totals.get('planned', 0.0) == 0.0:
                m_pl = re.search(r'(?:Total\s+Approved\s+Capital|Total\s+Contract\s+Value|Total\s+Approved|Approved\s+Capital|Total\s+Budget|Approved\s+Budget)[:\s]+(?:\$|USD\s*)?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|\d+(?:\.\d+)?)\s*(?:USD|[KkMm])?', p, re.IGNORECASE)
                if m_pl:
                    totals['planned'] = clean_numeric_str(m_pl.group(0))
            if totals.get('actual', 0.0) == 0.0:
                m_ac = re.search(r'(?:Total\s+Spend|Budget\s+Spent|Actual\s+Spend)[:\s]+(?:\$|USD\s*)?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|\d+(?:\.\d+)?)\s*(?:USD|[KkMm])?', p, re.IGNORECASE)
                if m_ac:
                    totals['actual'] = clean_numeric_str(m_ac.group(0))
        if totals.get('planned', 0.0) > 0.0 and totals.get('actual', 0.0) > 0.0 and totals.get('variance', 0.0) == 0.0:
            totals['variance'] = totals['planned'] - totals['actual']

    return {
        'categories_raw': categories_raw,
        'line_items_raw': line_items_raw,
        'milestones_raw': milestones_raw,
        'steerco_forecasts': steerco_forecasts,
        'totals': totals
    }

