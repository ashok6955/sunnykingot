# Telegram QR Image Bot

Ye bot user ke `qr` likhne par `images` folder se ek image bhejta hai. Images 1 by 1 send hoti hain, aur last image ke baad phir starting se sequence repeat hota hai.

## Setup

1. Bot token banaye:
   - Telegram me `@BotFather` open karein.
   - `/newbot` command chalayein.
   - Bot token copy karein.

2. Dependencies install karein:

```powershell
pip install -r requirements.txt
```

3. Apni QR/images add karein:

```text
images/
  01.png
  02.jpg
  03.webp
```

Images filename ke alphabetical order me send hongi. Isliye `01.png`, `02.png`, `03.png` jaisa naming best hai.

Chart image ke liye ek fixed image yahan add karein:

```text
chart_image/
  chart.png
```

4. Bot token set karke bot run karein:

```powershell
$env:TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN"
python bot.py
```

## Free Hosting: Render

Render ka free web service use karke bot online rakh sakte hain. Free service idle hone par sleep hoti hai, isliye kabhi-kabhi first reply 30-60 seconds late aa sakta hai.

1. Project ko GitHub par upload karein.
2. [Render](https://render.com/) par free account banayein.
3. Render Dashboard me **New** > **Blueprint** select karein.
4. Apna GitHub repo connect karein.
5. Environment variables add karein:

```text
TELEGRAM_BOT_TOKEN=BotFather se mila token
WEBHOOK_URL=https://aapka-render-service-url.onrender.com
```

6. Deploy complete hone ke baad Telegram me bot ko `qr` bhejein.

Note: Free Render service ka filesystem temporary hota hai. Bot restart/sleep ke baad sequence first image se start ho sakta hai.

## Use

Telegram me bot ko message bhejein:

```text
qr
```

Ya command:

```text
/qr
```

Chart image ke liye message ke andar kahin bhi `chart` ya `चार्ट` likhein:

```text
chart dikhao
```

Ya:

```text
मुझे चार्ट भेजो
```

QR image ke liye message ke andar kahin bhi `qr`, `क्यूआर`, `scan`, ya `scanner` likhein.

Har chat/user ke liye next image ka number `state.json` me save hota hai, isliye bot restart hone ke baad bhi sequence continue rahega.
