"""Prompts and the user-facing notices around cloud AI.

The system instruction is short on purpose: a small prompt is cheaper per request (the
free tier is rate-limited), and the fewer instructions a model has to follow, the fewer it
gets wrong. Everything about *acting* on the PC is deliberately out of scope - the local
command layer owns that, and this prompt tells the model to stay out of it.
"""

from __future__ import annotations

#: Personality + language rules. Kept under ~700 characters.
SYSTEM_PROMPT = """आप श्रद्धा हैं - एक विनम्र, संक्षिप्त हिन्दी सहायक जो Windows कंप्यूटर पर चलती है।

नियम:
1. भाषा वही रखिए जिसमें उपयोगकर्ता ने लिखा है - हिन्दी (देवनागरी), Hinglish (रोमन) या English.
2. उत्तर 2-4 छोटे वाक्यों में दीजिए। बहुत लंबा न लिखिए।
3. आप तकनीकी रूप से बात कर सकती हैं, पर कंप्यूटर पर कोई काम नहीं कर सकतीं:
   ऐप खोलना, फाइल खोलना, बंद करना - ये सब स्थानीय आदेश-प्रणाली करती है, आप नहीं।
   अगर उपयोगकर्ता कहे "Chrome खोलो", तो समझाइए कि यह स्थानीय आदेश है, आप खुद नहीं खोल सकतीं।
4. कभी भी कोई सिस्टम कमांड, स्क्रिप्ट, PowerShell या shell निर्देश न लिखिए।
5. अनिश्चित हों तो साफ़ कहिए कि आपको नहीं पता - मनगढ़ंत जवाब न दीजिए।
6. सुरक्षा या निजता से जुड़ी बातों में सलाह सावधानी से दीजिए।"""

#: Shown once, in chat, before any request may leave the machine.
CONSENT_NOTICE = (
    "क्लाउड AI अभी बंद है - आपके सवाल आपके कंप्यूटर से बाहर नहीं जाते।\n\n"
    "अगर आप Google Gemini का जवाब चालू करना चाहें, तो लिखिए: "
    "\"क्लाउड AI चालू करो\"\n"
    "ध्यान दीजिए: तब आपका सवाल Google को भेजा जाएगा। मुफ़्त स्तर पर Google "
    "उन सवालों का उपयोग अपने मॉडल सुधारने के लिए कर सकता है। "
    "ऐप खोलने/बंद करने जैसे काम फिर भी स्थानीय रहेंगे।\n\n"
    "(Cloud AI is off. Nothing leaves this computer until you explicitly enable it.)"
)

#: Confirmation after consent is granted.
CONSENT_GRANTED = (
    "ठीक है - क्लाउड AI चालू कर दिया। अब मुश्किल सवालों के जवाब Google Gemini से आएंगे। "
    "बंद करने के लिए लिखिए: \"क्लाउड AI बंद करो\"।"
)

CONSENT_REVOKED = (
    "क्लाउड AI बंद कर दिया। अब सब कुछ पहले की तरह आपके कंप्यूटर पर ही चलेगा।"
)

#: Phrases that grant consent. Exact, deliberate wording only - never fuzzy matched.
CONSENT_PHRASES = (
    "क्लाउड ai चालू करो",
    "क्लाउड ai चालू करो।",
    "क्लाउड ai ऑन करो",
    "क्लाउड ai बंद करो",
    "क्लाउड ai ऑफ करो",
    "enable cloud ai",
    "turn on cloud ai",
    "disable cloud ai",
    "turn off cloud ai",
)
REVOKE_PHRASES = (
    "क्लाउड ai बंद करो",
    "क्लाउड ai ऑफ करो",
    "disable cloud ai",
    "turn off cloud ai",
)

NO_KEY_NOTICE = (
    "क्लाउड AI सेट नहीं है: कोई API कुंजी नहीं मिली।\n"
    "कुंजी जोड़ने के लिए: python -m shraddha --set-api-key\n"
    "(या GEMINI_API_KEY environment variable सेट कीजिए)"
)

UNREACHABLE_NOTICE = "क्लाउड AI से जवाब नहीं आ सका - स्थानीय जवाब दिया जा रहा है।"


def build_system_prompt(extra: str | None = None) -> str:
    """The instruction sent with every request (kept stable for cacheability)."""
    if not extra:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n\n{extra.strip()}"


__all__ = [
    "CONSENT_GRANTED",
    "CONSENT_NOTICE",
    "CONSENT_PHRASES",
    "CONSENT_REVOKED",
    "NO_KEY_NOTICE",
    "REVOKE_PHRASES",
    "SYSTEM_PROMPT",
    "UNREACHABLE_NOTICE",
    "build_system_prompt",
]
