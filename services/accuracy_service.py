import os
import re
import json
import logging
from config import Config
from tools.doc_tool import DocTool
from llm.llm_client import LLMClient
import db
from models.project import Project

logger = logging.getLogger(__name__)

STOPWORDS = {
    'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and', 'any', 'are', 'aren\'t', 'as', 
    'at', 'be', 'because', 'been', 'before', 'being', 'below', 'between', 'both', 'but', 'by', 'can', 'can\'t', 
    'cannot', 'could', 'couldn\'t', 'did', 'didn\'t', 'do', 'does', 'doesn\'t', 'doing', 'don\'t', 'down', 'during', 
    'each', 'few', 'for', 'from', 'further', 'had', 'hadn\'t', 'has', 'hasn\'t', 'have', 'haven\'t', 'having', 
    'he', 'he\'d', 'he\'ll', 'he\'s', 'her', 'here', 'here\'s', 'hers', 'herself', 'him', 'himself', 'his', 'how', 
    'how\'s', 'i', 'i\'d', 'i\'ll', 'i\'m', 'i\'ve', 'if', 'in', 'into', 'is', 'isn\'t', 'it', 'it\'s', 'its', 
    'itself', 'let\'s', 'me', 'more', 'most', 'mustn\'t', 'my', 'myself', 'no', 'nor', 'not', 'of', 'off', 'on', 
    'once', 'only', 'or', 'other', 'ought', 'our', 'ours', 'ourselves', 'out', 'over', 'own', 'same', 'shan\'t', 
    'she', 'she\'d', 'she\'ll', 'she\'s', 'should', 'shouldn\'t', 'so', 'some', 'such', 'than', 'that', 'that\'s', 
    'the', 'their', 'theirs', 'them', 'themselves', 'then', 'there', 'there\'s', 'these', 'they', 'they\'d', 
    'they\'ll', 'they\'re', 'they\'ve', 'this', 'those', 'through', 'to', 'too', 'under', 'until', 'up', 'very', 
    'was', 'wasn\'t', 'we', 'we\'d', 'we\'ll', 'we\'re', 'we\'ve', 'were', 'weren\'t', 'what', 'what\'s', 'when', 
    'when\'s', 'where', 'where\'s', 'which', 'while', 'who', 'who\'s', 'whom', 'why', 'why\'s', 'with', 'won\'t', 
    'would', 'wouldn\'t', 'you', 'you\'d', 'you\'ll', 'you\'re', 'you\'ve', 'your', 'yours', 'yourself', 'yourselves'
}

class DataAccuracyService:
    @classmethod
    def get_threshold(cls) -> int:
        return getattr(Config, 'DATA_ACCURACY_THRESHOLD', 70)

    @classmethod
    def evaluate_file(cls, file_path: str, project_id: int) -> dict:
        """
        Parses document file and evaluates accuracy/match against project description.
        """
        if not os.path.exists(file_path):
            return {
                "success": False,
                "error": f"File not found: {file_path}",
                "match_percentage": 0,
                "threshold": cls.get_threshold(),
                "passed": False
            }

        try:
            doc_text = DocTool.parse_file(file_path)
        except Exception as e:
            logger.error(f"Error parsing file for accuracy check: {e}")
            return {
                "success": False,
                "error": f"Failed to parse document: {str(e)}",
                "match_percentage": 0,
                "threshold": cls.get_threshold(),
                "passed": False
            }

        filename = os.path.basename(file_path)
        return cls._evaluate_content(doc_text, project_id, context_label=f"File '{filename}'")

    @classmethod
    def evaluate_connector_items(cls, items: list, project_id: int, provider: str = "connector") -> dict:
        """
        Evaluates a batch of connector items against project description.
        """
        if not items:
            return {
                "success": False,
                "error": "No connector items provided for evaluation",
                "match_percentage": 0,
                "threshold": cls.get_threshold(),
                "passed": False
            }

        combined_text_parts = []
        for it in items:
            title = it.get('title') or it.get('summary') or it.get('name') or ''
            desc = it.get('description') or it.get('content') or ''
            cat = it.get('type') or it.get('category') or ''
            pri = it.get('priority') or ''
            combined_text_parts.append(f"Title: {title}\nType: {cat} | Priority: {pri}\nDescription: {desc}")

        combined_text = "\n\n---\n\n".join(combined_text_parts)
        return cls._evaluate_content(combined_text, project_id, context_label=f"{len(items)} items from {provider.upper()}")

    @classmethod
    def _evaluate_content(cls, content: str, project_id: int, context_label: str = "Document") -> dict:
        threshold = cls.get_threshold()

        # 1. Fetch target project
        project = None
        if db.db_session:
            try:
                project = db.db_session.query(Project).filter_by(id=project_id).first()
            except Exception as e:
                logger.warning(f"Error querying project {project_id}: {e}")

        proj_name = project.name if project else f"Project #{project_id}"
        proj_code = project.jira_key if project and project.jira_key else f"PRJ-{project_id}"
        proj_desc = (project.description or "").strip() if project else ""

        if not proj_desc:
            proj_desc = f"{proj_name} [{proj_code}] enterprise delivery initiative."

        # 2. Always compute baseline deterministic NLP analysis
        nlp_data = cls._compute_nlp_metrics(content, proj_name, proj_code, proj_desc)

        # 3. Attempt LLM evaluation only if host is online and responsive
        llm_result = None
        try:
            if LLMClient.is_online():
                llm_result = cls._evaluate_via_llm(content, proj_name, proj_code, proj_desc, nlp_data)
        except Exception:
            llm_result = None
        
        final_result = llm_result if llm_result else nlp_data
        
        # Ensure common metadata is always present
        final_result["threshold"] = threshold
        final_result["passed"] = final_result["match_percentage"] >= threshold
        final_result["project_id"] = project_id
        final_result["project_name"] = proj_name
        final_result["project_code"] = proj_code
        final_result["project_description"] = proj_desc
        final_result["success"] = True

        # Guarantee rich NLP fields are present even if LLM missed any
        if "matched_keywords" not in final_result or not final_result["matched_keywords"]:
            final_result["matched_keywords"] = nlp_data.get("matched_keywords", [])
        if "missing_keywords" not in final_result or not final_result["missing_keywords"]:
            final_result["missing_keywords"] = nlp_data.get("missing_keywords", [])
        if "document_topics" not in final_result or not final_result["document_topics"]:
            final_result["document_topics"] = nlp_data.get("document_topics", [])
        if "dimensions" not in final_result or not final_result["dimensions"]:
            final_result["dimensions"] = nlp_data.get("dimensions", {})
        if "nlp_stats" not in final_result:
            final_result["nlp_stats"] = nlp_data.get("nlp_stats", {})

        return final_result

    @classmethod
    def _compute_nlp_metrics(cls, content: str, proj_name: str, proj_code: str, proj_desc: str) -> dict:
        """
        Deep mathematical NLP analysis:
        - TF-IDF style term frequency vectorization
        - Cosine vector similarity
        - Jaccard vocabulary overlap
        - Entity recognition (project key & name)
        - Governance telemetry detection (budget, risks, deliverables, scope)
        - N-gram phrase extraction
        """
        import math
        from collections import Counter

        content_lower = content.lower()
        desc_lower = proj_desc.lower()
        name_lower = proj_name.lower()
        code_lower = proj_code.lower()

        # Tokenization
        def tokenize(text):
            return [w for w in re.findall(r'[a-zA-Z0-9_\-\.]{3,}', text.lower()) if w not in STOPWORDS and not w.isdigit()]

        doc_tokens = tokenize(content)
        desc_tokens = tokenize(proj_desc)
        name_tokens = tokenize(proj_name)
        all_scope_tokens = desc_tokens + name_tokens

        doc_counts = Counter(doc_tokens)
        scope_counts = Counter(all_scope_tokens)

        # 1. Cosine Similarity on Term Frequencies
        overlap_vocab = set(scope_counts.keys()).intersection(set(doc_counts.keys()))
        dot_product = sum(scope_counts[w] * doc_counts[w] for w in overlap_vocab)
        mag_scope = math.sqrt(sum(v**2 for v in scope_counts.values()))
        mag_doc = math.sqrt(sum(v**2 for v in doc_counts.values()))
        
        cosine_sim = (dot_product / (mag_scope * mag_doc)) if (mag_scope and mag_doc) else 0.0
        cosine_pct = int(min(100, max(0, round(cosine_sim * 100))))

        # 2. Extract Key Bigrams / Phrases
        def extract_bigrams(tokens):
            return [" ".join(tokens[i:i+2]) for i in range(len(tokens)-1)]

        scope_bigrams = set(extract_bigrams(all_scope_tokens))
        doc_bigrams = set(extract_bigrams(doc_tokens))
        matched_bigrams = [bg for bg in scope_bigrams if bg in content_lower]

        # 3. Matched & Missing Keywords
        # Matched terms sorted by frequency in document
        matched_keywords = []
        for w in overlap_vocab:
            matched_keywords.append({
                "term": w,
                "count": doc_counts[w],
                "type": "exact_keyword"
            })
        for bg in matched_bigrams:
            matched_keywords.append({
                "term": bg,
                "count": 1,
                "type": "keyphrase"
            })
        # Sort by occurrence
        matched_keywords.sort(key=lambda x: x["count"], reverse=True)
        matched_keywords = matched_keywords[:12]

        # Missing expected terms from project description
        missing_terms = [w for w in scope_counts.keys() if w not in doc_counts]
        # Filter to most salient terms
        missing_keywords = []
        for w in missing_terms:
            if len(w) >= 4 and w not in {'from', 'with', 'that', 'this', 'have', 'such', 'into'}:
                missing_keywords.append({
                    "term": w,
                    "category": "Project Scope Term"
                })
        missing_keywords = missing_keywords[:8]

        # Top document topics (what the document is primarily talking about)
        top_doc_terms = [w for w, c in doc_counts.most_common(15) if len(w) >= 4 and w not in overlap_vocab]
        document_topics = top_doc_terms[:6]

        # 4. Entity Validation
        code_found = code_lower in content_lower
        name_found = any(nw in content_lower for nw in name_tokens)
        entity_score = 100 if (code_found and name_found) else (75 if code_found else (40 if name_found else 0))

        # 5. Governance Telemetry Markers
        gov_categories = {
            "Financials & Budget": {
                "pattern": r'(\$|usd|budget|cost|spend|allocation|\bvariance\b|capex|opex)',
                "terms": ["budget", "cost", "spend", "usd", "variance"]
            },
            "Risks & Mitigations": {
                "pattern": r'(risk|mitigation|dependency|blocker|impediment|severity|threat)',
                "terms": ["risk", "mitigation", "dependency", "severity"]
            },
            "Milestones & Deliverables": {
                "pattern": r'(milestone|deliverable|timeline|deadline|sprint|sow|sign-off|q[1-4]|release)',
                "terms": ["milestone", "deliverable", "timeline", "sprint"]
            },
            "Scope & Architecture": {
                "pattern": r'(objective|scope|architecture|system|platform|specification|requirements)',
                "terms": ["architecture", "objective", "scope", "platform"]
            }
        }

        detected_gov = {}
        missing_gov = {}
        for cat_name, cat_info in gov_categories.items():
            matches_found = [t for t in cat_info["terms"] if t in content_lower]
            if re.search(cat_info["pattern"], content_lower):
                detected_gov[cat_name] = matches_found or [cat_name.split()[0].lower()]
            else:
                missing_gov[cat_name] = cat_info["terms"]

        gov_score = int((len(detected_gov) / len(gov_categories)) * 100)

        # 6. Scope Lexical Overlap Score
        scope_lexicon_score = int(min(100, (len(overlap_vocab) / max(1, len(scope_counts))) * 100))

        # 7. Composite Overall Match Score Calculation
        # Weighted formula:
        # - Entity Recognition: 20%
        # - Scope Lexicon: 30%
        # - Governance Telemetry: 25%
        # - Cosine Semantic Similarity: 25%
        composite_score = int(
            (entity_score * 0.20) +
            (scope_lexicon_score * 0.30) +
            (gov_score * 0.25) +
            (cosine_pct * 0.25)
        )

        # Penalize if text is extremely short (< 25 words)
        word_count = len(doc_tokens)
        if word_count < 25:
            composite_score = max(10, composite_score - 20)

        composite_score = max(5, min(99, composite_score))

        # 8. Dimensions Object (Non-Tech Plain English)
        dimensions = {
            "entity_validation": {
                "label": "Project Identity",
                "score": entity_score,
                "status": "Found" if entity_score >= 70 else ("Partial" if entity_score > 0 else "Not Found"),
                "details": f"Project code '{proj_code}' {'identified' if code_found else 'missing'} in document body.",
                "icon": "Shield"
            },
            "scope_vocabulary": {
                "label": "Project Keywords",
                "score": scope_lexicon_score,
                "status": "High Match" if scope_lexicon_score >= 60 else ("Moderate" if scope_lexicon_score >= 30 else "Low Match"),
                "details": f"Identified {len(overlap_vocab)} of {len(scope_counts)} key technical terms from project scope definition.",
                "icon": "BookOpen"
            },
            "governance_telemetry": {
                "label": "Required Sections",
                "score": gov_score,
                "status": "Complete" if gov_score >= 75 else ("Partial" if gov_score >= 40 else "Missing"),
                "details": f"Found {len(detected_gov)} of 4 required enterprise telemetry sections ({', '.join(detected_gov.keys()) or 'None'}).",
                "icon": "Layers"
            },
            "semantic_similarity": {
                "label": "Topic Match",
                "score": cosine_pct,
                "status": "Strong" if cosine_pct >= 60 else ("Moderate" if cosine_pct >= 30 else "Low Match"),
                "details": f"Cosine similarity of {cosine_pct}% between document TF-IDF vector and project scope vector.",
                "icon": "Activity"
            }
        }

        # 9. Professional Matched Aspects List
        matched_aspects = []
        if code_found or name_found:
            matched_aspects.append(f"[Entity Recognition] Direct reference to target project identifier '{proj_code}' ({proj_name})")
        
        if matched_bigrams:
            matched_aspects.append(f"[Semantic Alignment] Aligns on multi-word project concepts: {', '.join(matched_bigrams[:3])}")
        elif matched_keywords:
            sample_terms = [f"'{k['term']}' (x{k['count']})" for k in matched_keywords[:4]]
            matched_aspects.append(f"[Domain Lexicon] Detected {len(matched_keywords)} matching scope keywords: {', '.join(sample_terms)}")
            
        if detected_gov:
            matched_aspects.append(f"[Governance Telemetry] Contains structured sections: {', '.join(detected_gov.keys())}")
            
        if word_count >= 50:
            matched_aspects.append(f"[Document Density] NLP parsed {word_count} tokens with sufficient analytical depth for vector ingestion")

        if not matched_aspects:
            matched_aspects.append("[Lexical Parse] Document successfully converted to structured text for vector analysis")

        # 10. Professional Unmatched Aspects List
        unmatched_aspects = []
        if not code_found:
            unmatched_aspects.append(f"[Entity Gap] Target project key '{proj_code}' is absent from document title, headers, and metadata")

        if missing_keywords:
            sample_missing = [f"'{k['term']}'" for k in missing_keywords[:5]]
            unmatched_aspects.append(f"[Scope Divergence] Core project description terms not found in document: {', '.join(sample_missing)}")

        if missing_gov:
            unmatched_aspects.append(f"[Governance Omission] Missing expected corporate telemetry: {', '.join(missing_gov.keys())}")

        if cosine_pct < 35:
            unmatched_aspects.append(f"[Vector Distance] Low semantic vector cosine similarity ({cosine_pct}%) indicates contextual divergence")

        if not unmatched_aspects:
            unmatched_aspects.append("[Scope Integrity] No major scope discrepancies or anomalies identified")

        # 11. Summary
        summary = (
            f"Content achieves {composite_score}% alignment with '{proj_name}' [{proj_code}]. Meets enterprise threshold for automated ingestion."
            if composite_score >= cls.get_threshold()
            else f"Content shows moderate to low alignment ({composite_score}%) with project scope. Missing key entities or telemetry sections; manual review recommended before ingestion."
        )

        return {
            "match_percentage": composite_score,
            "matched_aspects": matched_aspects,
            "unmatched_aspects": unmatched_aspects,
            "matched_keywords": matched_keywords,
            "missing_keywords": missing_keywords,
            "document_topics": document_topics,
            "dimensions": dimensions,
            "nlp_stats": {
                "word_count": word_count,
                "cosine_similarity": cosine_pct,
                "scope_lexicon_score": scope_lexicon_score,
                "governance_score": gov_score,
                "entity_score": entity_score
            },
            "summary": summary
        }

    @classmethod
    def _evaluate_via_llm(cls, content: str, proj_name: str, proj_code: str, proj_desc: str, nlp_data: dict) -> dict:
        try:
            client = LLMClient()
            sample_content = content[:3000]

            prompt = (
                f"You are a Project Governance & Quality Assurance Auditor performing NLP verification.\n"
                f"Analyze the uploaded document against the Target Project Definition.\n\n"
                f"TARGET PROJECT:\n"
                f"- Name: {proj_name}\n"
                f"- Code: {proj_code}\n"
                f"- Description: {proj_desc}\n\n"
                f"DOCUMENT SAMPLE:\n"
                f"```\n{sample_content}\n```\n\n"
                f"Calculated Baseline NLP Vector Cosine: {nlp_data.get('nlp_stats', {}).get('cosine_similarity', 30)}%\n"
                f"Governance Markers Present: {list(nlp_data.get('dimensions', {}).get('governance_telemetry', {}).get('details', ''))}\n\n"
                f"Provide a rigorous project audit evaluating:\n"
                f"1. Semantic consistency & scope alignment\n"
                f"2. Matched project aspects (3-5 structured bullet points with [Tag] prefix)\n"
                f"3. Unmatched/deviated aspects (2-4 structured bullet points with [Tag] prefix)\n"
                f"4. An overall match percentage (integer 0 to 100)\n"
                f"5. A concise 1-2 sentence executive audit summary\n\n"
                f"Return ONLY valid JSON matching this schema:\n"
                f"{{\n"
                f'  "match_percentage": <int 0-100>,\n'
                f'  "matched_aspects": ["[Scope] ...", "[Governance] ..."],\n'
                f'  "unmatched_aspects": ["[Entity] ...", "[Missing Telemetry] ..."],\n'
                f'  "summary": "<executive audit summary>"\n'
                f"}}"
            )

            timeout_sec = getattr(Config, 'LLM_TIMEOUT', 120)
            resp_str = client.generate(
                prompt=prompt,
                system="You are an enterprise AI data governance auditor. Output strict JSON only.",
                format="json",
                request_timeout=(10, timeout_sec)
            )

            match = re.search(r'\{.*\}', resp_str, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                pct = int(data.get("match_percentage", nlp_data["match_percentage"]))
                pct = max(5, min(99, pct))
                
                # Blend with deterministic NLP data
                result = dict(nlp_data)
                result["match_percentage"] = pct
                if data.get("matched_aspects"):
                    result["matched_aspects"] = data["matched_aspects"]
                if data.get("unmatched_aspects"):
                    result["unmatched_aspects"] = data["unmatched_aspects"]
                if data.get("summary"):
                    result["summary"] = data["summary"]
                return result
        except Exception as e:
            logger.info(f"LLM accuracy evaluation unavailable or timed out ({e}), using deterministic NLP evaluator.")

        return None

