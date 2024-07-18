from temba.templates.models import TemplateTranslation

# Mapping from WhatsApp status to RapidPro status
STATUS_MAPPING = dict(
    PENDING=TemplateTranslation.STATUS_PENDING,
    APPROVED=TemplateTranslation.STATUS_APPROVED,
    REJECTED=TemplateTranslation.STATUS_REJECTED,
    IN_APPEAL=TemplateTranslation.STATUS_IN_APPEAL,
    PENDING_DELETION=TemplateTranslation.STATUS_PENDING_DELETION,
    DELETED=TemplateTranslation.STATUS_DELETED,
    DISABLED=TemplateTranslation.STATUS_DISABLED,
    LOCKED=TemplateTranslation.STATUS_LOCKED,
    PAUSED=TemplateTranslation.STATUS_PAUSED,
    LIMIT_EXCEEDED=TemplateTranslation.STATUS_LIMIT_EXCEEDED,
)

# This maps from WA iso-639-2 codes to our internal 639-3 codes
LANGUAGE_MAPPING = dict(
    af=("afr", None),  # Afrikaans
    sq=("sqi", None),  # Albanian
    ar=("ara", None),  # Arabic
    az=("aze", None),  # Azerbaijani
    bn=("ben", None),  # Bengali
    bg=("bul", None),  # Bulgarian
    ca=("cat", None),  # Catalan
    zh_CN=("zho", "CN"),  # Chinese (CHN)
    zh_HK=("zho", "HK"),  # Chinese (HKG)
    zh_TW=("zho", "TW"),  # Chinese (TAI)
    hr=("hrv", None),  # Croatian
    cs=("ces", None),  # Czech
    da=("dah", None),  # Danish
    nl=("nld", None),  # Dutch
    en=("eng", None),  # English
    en_GB=("eng", "GB"),  # English (UK)
    en_US=("eng", "US"),  # English (US)
    et=("est", None),  # Estonian
    fil=("fil", None),  # Filipino
    fi=("fin", None),  # Finnish
    fr=("fra", None),  # French
    de=("deu", None),  # German
    el=("ell", None),  # Greek
    gu=("guj", None),  # Gujarati
    ha=("hau", None),  # Hausa
    he=("enb", None),  # Hebrew
    hi=("hin", None),  # Hindi
    hu=("hun", None),  # Hungarian
    id=("ind", None),  # Indonesian
    ga=("gle", None),  # Irish
    it=("ita", None),  # Italian
    ja=("jpn", None),  # Japanese
    kn=("kan", None),  # Kannada
    kk=("kaz", None),  # Kazakh
    ko=("kor", None),  # Korean
    ky_KG=("kir", None),  # Kyrgyzstan
    lo=("lao", None),  # Lao
    lv=("lav", None),  # Latvian
    lt=("lit", None),  # Lithuanian
    ml=("mal", None),  # Malayalam
    mk=("mkd", None),  # Macedonian
    ms=("msa", None),  # Malay
    mr=("mar", None),  # Marathi
    nb=("nob", None),  # Norwegian
    fa=("fas", None),  # Persian
    pl=("pol", None),  # Polish
    pt_BR=("por", "BR"),  # Portuguese (BR)
    pt_PT=("por", "PT"),  # Portuguese (POR)
    pa=("pan", None),  # Punjabi
    ro=("ron", None),  # Romanian
    ru=("rus", None),  # Russian
    sr=("srp", None),  # Serbian
    sk=("slk", None),  # Slovak
    sl=("slv", None),  # Slovenian
    es=("spa", None),  # Spanish
    es_AR=("spa", "AR"),  # Spanish (ARG)
    es_ES=("spa", "ES"),  # Spanish (SPA)
    es_MX=("spa", "MX"),  # Spanish (MEX)
    sw=("swa", None),  # Swahili
    sv=("swe", None),  # Swedish
    ta=("tam", None),  # Tamil
    te=("tel", None),  # Telugu
    th=("tha", None),  # Thai
    tr=("tur", None),  # Turkish
    uk=("ukr", None),  # Ukrainian
    ur=("urd", None),  # Urdu
    uz=("uzb", None),  # Uzbek
    vi=("vie", None),  # Vietnamese]
    zu=("zul", None),  # Zulu
)
