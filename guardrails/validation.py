from functools import wraps
from pydantic import BaseModel, ValidationError
from typing import Type
import logging

logger = logging.getLogger(__name__)

def validate_input(schema: Type[BaseModel]):
    """
    Decorator to validate input dictionaries against a Pydantic schema.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, input_data, *args, **kwargs):
            try:
                validated_data = schema(**input_data)
                return func(self, validated_data.model_dump(), *args, **kwargs)
            except ValidationError as e:
                logger.error(f"Input validation failed for {self.__class__.__name__}: {e}")
                raise ValueError(f"Input validation failed: {e}")
        return wrapper
    return decorator

def validate_output(schema: Type[BaseModel]):
    """
    Decorator to validate output dictionaries against a Pydantic schema.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            result = func(self, *args, **kwargs)
            try:
                if isinstance(result, dict) and "result" in result:
                     schema(**result["result"])
                else:
                     schema(**result)
                return result
            except ValidationError as e:
                logger.error(f"Output validation failed for {self.__class__.__name__}: {e}")
                # Depending on strictness, we might return an error structure instead of raising
                return {"status": "error", "error": f"Output validation failed: {e}"}
        return wrapper
    return decorator
