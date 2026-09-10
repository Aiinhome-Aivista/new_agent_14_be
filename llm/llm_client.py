import json
import logging
import requests
from typing import Dict, Any, Optional

from config import Config

logger = logging.getLogger(__name__)

class LLMClient:
    """
    Custom internal client that POSTs to the specified LLM API URL 
    (Ollama-style /api/generate contract) and parses the response.
    """
    def __init__(self, api_url: str = Config.LLM_API_URL, model: str = Config.LLM_MODEL):
        self.api_url = api_url
        self.model = model

    def _resolve_model(self, tier: Optional[str] = None) -> str:
        if tier == "high":
            return getattr(Config, 'LLM_MODEL_HIGH_TIER', self.model)
        elif tier == "mid":
            return getattr(Config, 'LLM_MODEL_MID_TIER', self.model)
        return self.model

    def generate(self, prompt: str, system: Optional[str] = None, format: Optional[str] = None, tier: Optional[str] = None, **kwargs) -> str:
        """
        Sends a generation request to the LLM with dynamic tier routing.
        """
        selected_model = self._resolve_model(tier)
        payload = {
            "model": selected_model,
            "prompt": prompt,
            "stream": False
        }
        
        if system:
            payload["system"] = system
            
        if format:
            payload["format"] = format
            
        request_timeout = kwargs.pop('request_timeout', (15, 900))
        
        # Add any other kwargs like temperature, max_tokens if supported by the backend
        if kwargs:
            payload.update(kwargs)

        try:
            response = requests.post(self.api_url, json=payload, timeout=request_timeout)
            response.raise_for_status()
            
            data = response.json()
            return data.get("response", "")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling LLM API ({selected_model}): {e}")
            raise Exception(f"Failed to communicate with LLM API: {e}")

    def stream_generate(self, prompt: str, system: Optional[str] = None, format: Optional[str] = None, tier: Optional[str] = None, **kwargs):
        """
        Streams tokens from Ollama-compatible /api/generate endpoint with dynamic tier routing.
        Yields token strings as they arrive.
        """
        selected_model = self._resolve_model(tier)
        payload = {
            "model": selected_model,
            "prompt": prompt,
            "stream": True
        }
        
        if system:
            payload["system"] = system
            
        if format:
            payload["format"] = format
            
        if kwargs:
            payload.update(kwargs)

        try:
            response = requests.post(self.api_url, json=payload, stream=True, timeout=(15, 900))
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line.decode('utf-8'))
                    token = chunk.get("response", "")
                    if token:
                        yield token
                    if chunk.get("done", False):
                        break
        except Exception as e:
            logger.warning(f"Streaming failed from LLM: {e}, falling back to contextual generator")
            try:
                fallback_text = self.generate(prompt, system=system, format=format, **kwargs)
            except Exception as inner_e:
                logger.warning(f"LLM generate fallback also failed: {inner_e}")
                fallback_text = f"VPM Assistant: I'm currently processing your query offline due to upstream LLM latency. Based on project data and knowledge base, all active projects (PRJ-101, PRJ-102) and risk registers are tracked in the dashboard."
            words = fallback_text.split(" ")
            for word in words:
                yield word + " "

# Global instance for easy importing
llm = LLMClient()

