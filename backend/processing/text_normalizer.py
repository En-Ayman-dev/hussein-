import re
import unicodedata
from typing import Dict, List, Optional, Union


class ArabicNormalizer:
    """Normalizer for Arabic text with search-optimized transformations."""

    # Arabic diacritics (harakat) to remove
    DIACRITICS = [
        '\u064b',  # Fathatan
        '\u064c',  # Dammatan
        '\u064d',  # Kasratan
        '\u064e',  # Fatha
        '\u064f',  # Damma
        '\u0650',  # Kasra
        '\u0651',  # Shadda
        '\u0652',  # Sukun
        '\u0653',  # Maddah
        '\u0654',  # Hamza above
        '\u0655',  # Hamza below
        '\u0656',  # Subscript alef
        '\u0657',  # Inverted damma
        '\u0658',  # Mark noon ghunna
        '\u0659',  # Zwarakay
        '\u065a',  # Vowel sign small v above
        '\u065b',  # Vowel sign inverted small v above
        '\u065c',  # Vowel sign dot below
        '\u065d',  # Reversed damma
        '\u065e',  # Fatha with two dots
        '\u065f',  # Wavy hamza below
        '\u0670',  # Superscript alef
    ]

    # Alef variants to normalize to standard alef
    ALEF_VARIANTS = {
        '\u0622': '\u0627',  # Alef with madda above → Alef
        '\u0623': '\u0627',  # Alef with hamza above → Alef
        '\u0625': '\u0627',  # Alef with hamza below → Alef
        '\u0627': '\u0627',  # Alef (already standard)
    }

    # Other common normalizations for search
    OTHER_NORMALIZATIONS = {
        '\u0629': '\u0647',  # Teh marbuta → Heh
        '\u0649': '\u064a',  # Alef maksura → Ya
        '\u0640': '',        # Tatweel (elongation) → remove
    }

    def __init__(self):
        # Compile regex for diacritics removal
        self.diacritics_pattern = re.compile(f'[{"".join(self.DIACRITICS)}]')

        # Build translation table for character replacements
        self.translation_table = str.maketrans({
            **self.ALEF_VARIANTS,
            **self.OTHER_NORMALIZATIONS,
        })

    def normalize_text(self, text: str) -> str:
        """Normalize Arabic text for search purposes.

        Args:
            text: Input Arabic text

        Returns:
            Normalized text suitable for search
        """
        if not text:
            return ''

        # Convert to string if not already
        text = str(text)

        # Step 1: Unicode normalization (NFC form)
        text = unicodedata.normalize('NFC', text)

        # Step 2: Remove diacritics
        text = self.diacritics_pattern.sub('', text)

        # Step 3: Normalize character variants
        text = text.translate(self.translation_table)

        # Step 4: Lowercase (for mixed Arabic-Latin text)
        text = text.lower()

        # Step 5: Normalize whitespace
        text = re.sub(r'\s+', ' ', text.strip())

        return text

    def generate_normalized_label(self, text: str, max_length: Optional[int] = None) -> str:
        """Generate a normalized label optimized for search.

        Args:
            text: Input text
            max_length: Maximum length of the normalized label

        Returns:
            Normalized label
        """
        normalized = self.normalize_text(text)

        if max_length and len(normalized) > max_length:
            normalized = normalized[:max_length].rstrip()

        return normalized

    def normalize_list(self, texts: List[str]) -> List[str]:
        """Normalize a list of texts.

        Args:
            texts: List of input texts

        Returns:
            List of normalized texts
        """
        return [self.normalize_text(text) for text in texts]

    def normalize_dict_values(
        self,
        data: Dict[str, Union[str, List[str]]],
        keys_to_normalize: Optional[List[str]] = None
    ) -> Dict[str, Union[str, List[str]]]:
        """Normalize string values in a dictionary.

        Args:
            data: Dictionary with string or list values
            keys_to_normalize: Specific keys to normalize (None = all string keys)

        Returns:
            Dictionary with normalized values
        """
        result = {}

        for key, value in data.items():
            if keys_to_normalize and key not in keys_to_normalize:
                result[key] = value
                continue

            if isinstance(value, str):
                result[key] = self.normalize_text(value)
            elif isinstance(value, list):
                result[key] = [self.normalize_text(item) if isinstance(item, str) else item for item in value]
            else:
                result[key] = value

        return result


# Convenience functions
_normalizer = ArabicNormalizer()

def normalize_arabic_text(text: str) -> str:
    """Convenience function to normalize Arabic text."""
    return _normalizer.normalize_text(text)

def generate_search_label(text: str, max_length: Optional[int] = None) -> str:
    """Convenience function to generate normalized search label."""
    return _normalizer.generate_normalized_label(text, max_length)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Normalize Arabic text for search")
    parser.add_argument("text", help="Text to normalize")
    parser.add_argument("--max-length", type=int, help="Maximum length of normalized label")

    args = parser.parse_args()

    normalizer = ArabicNormalizer()
    normalized = normalizer.generate_normalized_label(args.text, args.max_length)

    print(json.dumps({
        "original": args.text,
        "normalized": normalized
    }, ensure_ascii=False, indent=2))