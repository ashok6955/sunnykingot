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

Current setup me `images` folder ki files `01` se `43` tak sequence me renamed hain, isliye bot ab unhe isi fixed order me bhejega.

Bot daily subah `4:00 AM` se `5:20 AM` tak `Asia/Kolkata` time ke hisaab se kaam nahi karega.
Configured source group ko bot daily subah `4:00 AM` par auto-lock aur `5:20 AM` par auto-unlock bhi karega, agar bot us group me admin hoke chat permissions manage kar sakta ho.

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
TARGET_GROUP_ID=-1004304577201
SOURCE_GROUP_ID=-1004304577201
RELAY_CHAT_ID=-1004304577201
ADMIN_FORUM_GROUP_ID=-1004304577201
OWNER_USER_ID=123456789
```

6. Deploy complete hone ke baad Telegram me bot ko `qr` bhejein.

Note: Free Render service ka filesystem temporary hota hai. Bot restart/sleep ke baad sequence first image se start ho sakta hai.
Free plan par kabhi-kabhi network delay ya sleep ki wajah se temporary timeout aa sakta hai. Bot me basic retry logic add hai, isliye short timeout me wo automatically dubara try karega.

## Use

Telegram me bot ko message bhejein:

```text
qr
```

Ya command:

```text
/qr
```

Group ID dekhne ke liye kisi group me `/groupid` likhein. Bot us group ka Telegram chat ID reply karega.

Target group dekhne ke liye `/targetgroup` likhein.

Target group set karne ke 2 tareeqe hain:

```text
/settargetgroup -1004304577201
```

Ya jis group ko target banana ho us group ke andar:

```text
/settargetgroup
```

Target group clear karne ke liye:

```text
/cleartargetgroup
```

Source group dekhne ke liye:

```text
/sourcegroup
```

Source group set karne ke 2 tareeqe hain:

```text
/setsourcegroup -1004304577201
```

Ya jis group ko source banana ho us group ke andar:

```text
/setsourcegroup
```

Relay chat dekhne ke liye:

```text
/relaychat
```

Relay chat set karne ke liye receiving private chat ya group ke andar:

```text
/setrelaychat
```

Compatibility ke liye `/adminforum` aur `/setadminforum` bhi kaam karte rahenge.

Iske baad bot sirf configured source group se receiving private chat/group me relay karega. Har user ki ek alag editable list banegi. Same user ki nayi game usi list message me add hoti rahegi.

Relay rules:

- Sirf configured source group se relay hoga
- Sirf valid game-number text relay hoga
- Photo, image document, screenshot relay nahi honge
- Random normal text, video, aur non-image file relay nahi honge
- Har user ka alag master list message banega
- Same user ki nayi entries usi list message me update hongi
- List format simple hoga: user name, `Games: N`, aur numbered game lines
- Har numbered game line ke beech blank line rahegi
- Supergroup/topics ki zaroorat nahi hai
- Agar `OWNER_USER_ID` set hai to settings commands sirf owner hi chala sakega

`ds ok` likhne par bot recent saved game messages ko target group me as a bot text bhej dega aur pehle source chat me `DISAWAR GAME OK ✔` reply karega. Beech me image ya normal text aaye to woh ignore honge. Agar kisi specific game message ko bhejna ho to us message par reply karke `ds ok` likhein.

Game total ke liye pehle game message bhejein, phir `total` ya `/total` likhein. Bot sirf latest recent game message ka total nikaalega. Agar kisi specific game message ka total chahiye ho to us message par reply karke `total` likh sakte hain.

Chart image ke liye message me exact word `chart`, `चार्ट`, `time`, ya `timing` likhein. `timeo` jaisi spelling par trigger nahi hoga:

```text
chart dikhao
```

Ya:

```text
मुझे चार्ट भेजो
```

QR image ke liye message ke andar kahin bhi `qr`, `क्यूआर`, `scan`, `scanner`, `barcode`, ya `bar code` likhein.

Har chat/user ke liye next image ka number `state.json` me save hota hai, isliye bot restart hone ke baad bhi sequence continue rahega.

Note: Subah `4:00 AM` se `6:00 AM` ke beech bot koi reply nahi bhejega.

## Telegram Business

Private customer chats me bot use karne ke liye Telegram me Business Mode enable karna zaroori hai:

1. `@BotFather` open karein.
2. `/mybots` bhejein.
3. Apna bot select karein.
4. `Bot Settings` > `Telegram Business` / `Business Mode` enable karein.
5. Telegram app me `Settings` > `Telegram Business` > `Chatbots` open karein.
6. Apna bot add karein aur `Reply to messages` allow karein.

Iske baad business private chats me user `qr`, `scan`, `scanner`, `barcode`, `bar code`, `chart`, ya `चार्ट` likhega to bot reply kar sakega.
