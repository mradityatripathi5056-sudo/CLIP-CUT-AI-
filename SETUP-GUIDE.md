# Clip Cut AI: Poora Setup Guide aur Features

Developed by **Aditya & Anshik**. Clip Cut AI open source hai (MIT licence, [LICENSE](LICENSE) dekho).

Ye app streamers ke YouTube/Twitch videos aur live streams se best moments khud dhoondhta hai, unhe captions, emojis,
music aur effects ke saath vertical Reels/Shorts banata hai, aur YouTube, Instagram, Facebook (aur Threads, Bluesky,
Discord) par tay time pe khud post karta hai.

---

## Part 1: Kya chahiye

| Cheez | Kahan se | Zaroori? |
|---|---|---|
| Computer (Windows/Mac/Linux) ya cloud server | Laptop ya Hostinger VPS (KVM 2) | Haan |
| Python 3.10 ya naya | python.org | Haan |
| ffmpeg | Windows: `winget install Gyan.FFmpeg` | Haan |
| AI key (Gemini free mein milti hai) | https://aistudio.google.com/apikey | Haan (bina key ke clips sirf awaaz se chune jaate hain) |
| Jagah (disk) | Shuru mein ~1.5 GB, kaam ke liye 20–50 GB free | Haan |
| Gmail app password | https://myaccount.google.com/apppasswords | Email login ke liye |

---

## Part 2: Laptop/PC pe install (Windows)

**Sabse aasaan:** ZIP ko `C:\clipcut` mein extract karo aur **START-WINDOWS.bat** pe double-click karo. Ye Python, ffmpeg
aur libraries khud install karta hai, app chalata hai aur browser khol deta hai. Pehli baar Python ya ffmpeg install
ho to window band karke .bat dobara chalana. Agli baar se bas double-click karna hai. (Mac/Linux: `START-MAC-LINUX.sh`.)

Haath se karna ho to:

1. ZIP ko `C:\clipcut` mein extract karo. Folder chhota aur pakka rakho. Downloads ya Desktop ke andar gehra mat rakho.
2. **Start** menu mein `cmd` kholo aur ye likho:
   ```
   winget install Python.Python.3.12
   winget install Gyan.FFmpeg
   ```
   (Install ke baad cmd band karke dobara kholo.)
3. App ke folder mein jao aur libraries daalo:
   ```
   cd C:\clipcut
   pip install -r requirements.txt
   ```
4. App chalao:
   ```
   python -m studio.server
   ```
   Pehli baar speech model (~480 MB) khud download hota hai, thoda ruk jao.
5. Browser mein kholo: **http://127.0.0.1:8765**
6. **Settings → AI** mein service chuno (Gemini), key paste karo, **Save and test** dabao.

> PC band hua to posting bhi rukegi. 24 ghante chalane ke liye Part 3 dekho.

## Part 2B: ClipCutAI.exe (ek click se)
- Folder mein **ClipCutAI.exe** pe double-click karo. App chhoti (minimise) window mein chalu ho jaata hai aur browser khud khulta hai.
- App pehle se chal raha ho to exe sirf browser mein app khol deta hai.
- Pehli baar Windows "Windows protected your PC" dikha sakta hai: **More info → Run anyway**.
- Exe ko Clip Cut AI folder ke andar hi rakhna. Desktop pe chahiye to right-click → **Send to → Desktop (create shortcut)**.
- Settings → Online mein **Start Clip Cut AI when Windows starts** on karoge to laptop on hote hi app chalu.

## Part 2C: Online with ngrok (laptop pe chalta hai, address https wala)
1. https://dashboard.ngrok.com pe free account banao.
2. **Your Authtoken** copy karo, aur **Domains** mein ngrok ka diya hua free domain copy karo (jaise `xyz.ngrok-free.dev`, apne aap milta hai).
3. Pehle **Settings → Login** mein apna email aur password save karo (online hone pe sign-in zaroori hai).
4. **Settings → Online** mein dono paste karo, **Go online** tick karo, **Save and restart** dabao.
5. App online address (`https://aapka-domain.ngrok-free.app`) pe khulega. Pehli baar ngrok ka page aaye to **Visit Site** dabao.
6. Online hone ke baad Google Cloud aur Meta app mein Settings → Online mein likhe redirect address daal do. Ab Facebook aur Instagram ke normal **Connect** button bhi chalenge.
- Online hone pe sign-up band ho jaata hai: sirf aap, aur jinhe aap Team mein add karo, login kar sakte hain.

## Part 3: Phone se chalana (cloud server, bina laptop ke)

1. Hostinger VPS (KVM 2, Ubuntu) lo. UPI/RuPay se payment ho jaata hai.
2. Ek domain lo aur uska `A` record server ke IP pe set karo.
3. Server pe ZIP upload karke ye chalao:
   ```
   unzip ClipCutAI.zip && cd ClipCutAI
   sudo bash deploy/vps-setup.sh
   ```
   Script Docker, HTTPS aur app sab set kar deta hai. Poori jaankari `DEPLOY.md` mein hai.
4. Phone pe `https://aapka-domain` kholo, sign up karo, phir Chrome menu se **Install app / Add to Home Screen** dabao.
   Ab ye phone pe app jaisa chalega.
5. Admin banne ke liye server pe:
   ```
   docker compose exec app python -m studio.admin grant aapka@gmail.com
   ```

---

## Part 4: Pehli baar setup (dashboard mein, step by step)

### Step 1: Email login (taaki kuch na ude)
**Settings → Login** (server pe: **Settings → Security**)
1. Google Account mein 2-Step Verification on karo.
2. https://myaccount.google.com/apppasswords pe "Clip Cut AI" naam se app password banao (16 letters).
3. **Email for codes** mein Gmail aur app password daalo, phir **Save** aur **Send a test** dabao.
4. **Your login** mein naam, email aur password daalo. Email pe 6-digit code aayega; wo daalo, login save ho jaayega.
5. **Two-step sign-in** on karo. Ab har login pe email code maanga jaayega.
6. "Email me the backup every Monday" on karo, taaki har hafte backup email pe aaye.

### Step 2: Accounts connect karo
**Settings → Connected apps**
- **YouTube:** Google Cloud mein OAuth client banao, ID aur secret paste karo, phir **Connect** dabao. Saare boxes tick karna (kamai dekhne ke liye bhi zaroori hai).
- **Instagram:** Meta app ka **Instagram App ID** daalo (Meta App ID nahi, warna "Invalid platform app" error aata hai).
- **Facebook + Instagram (Meta):** App ID, App Secret aur **Configuration ID** daalo, phir Connect. Isse Pages aur unse jude Instagram dono aa jaate hain.
- **Facebook (aasaan tareeka, token se):** "Connect with a key or token" mein **Facebook Page (easy way)** → Connect.
  1. https://developers.facebook.com/tools/explorer kholo, apna Meta app chuno, **User Token** chuno.
  2. Permissions add karo: pages_show_list, pages_read_engagement, pages_manage_posts, business_management, instagram_basic, instagram_content_publish. Phir **Generate Access Token** dabao aur apne Pages allow karo.
  3. Token copy karke https://developers.facebook.com/tools/debug/accesstoken kholo, **Debug** dabao, phir **Extend Access Token** dabao aur lamba token copy karo.
  4. App mein paste karke Connect dabao. Aapke saare Pages aur unse jude Instagram accounts aa jaayenge. Isme redirect ya https ki zaroorat nahi hai.
- **Threads / Bluesky / Discord / Telegram:** "More places to post" mein key ya webhook paste karo.
- Har page ke saamne language chuno: Auto, Hinglish ya English.

### Step 3: Channel add karo (sabse aasaan tareeka)
**Home → Add a YouTube channel**
1. Streamer ka channel link paste karo, jaise `https://www.youtube.com/@Mortal`.
2. Audience chuno: **India (Hinglish)** ya **Worldwide (English)**.
3. **Add and plan** dabao. App khud:
   - roz kitni reels jaayengi, wo tay karta hai (2 se 5);
   - time set karta hai (India: 12:30, 15:30, 18:30, 21:00, 22:30);
   - naye videos aur streams khud clip karke saare connected accounts pe post karta hai;
   - views aane ke baad timing best hours pe shift kar deta hai.

### Creator ka video bina link ke
Creator ke page pe upar **Pick a video** dabao: unki nayi videos aur purane streams ki list aati hai, **Clip this** dabao. Link paste karna ab optional hai.

### Step 4: Phone alerts
**Settings → Phone alerts → Turn on alerts on this phone.**
(iPhone pe pehle Home Screen pe add karo. Telegram bot bhi laga sakte ho buttons ke liye.)

### Step 5: Autopilot on karo
Har creator ki **Setup → Autopilot → Turn on everything** dabao. (Kuch features pehle se on hote hain.)

### Step 6: AI Manager on karo
**Manager** page pe switch on karo. Ye har ghante pages dekhta hai, fail hui posts dobara karta hai aur roz report deta hai.
Aap usse chat bhi kar sakte ho, jaise "Mortal ke daily 5 reels kar do".

---

## Part 5: Saare features

### Clip banana
- Video link, upload ya live stream se khud best moments dhoondhna: AI do tarah se jaanchta hai, kya bola gaya aur streamer/chat kitna excited tha.
- Live stream khud record hona jab streamer live aaye.
- Naye uploads khud clip hona (YouTube /videos, /streams aur Twitch).
- Captions kai styles mein, highlight words ke saath.
- **India ke liye Hinglish, baaki ke liye English** titles, hooks aur captions.
- Effects: zoom/shake, instant replay, sound effects, emojis, AI voice intro.
- **Background music** aapki library se (Settings → Music), mood ke hisaab se.
- **Reaction sticker:** aapki photo bade moment pe aati hai.
- Aapka logo aur streamer ka credit har clip pe.
- **Best clip length** views se khud seekhta hai.
- Weekly compilation (top 10 clips ka lamba YouTube video, thumbnail aur chapters ke saath).
- Trending page: game ke trending videos aur hashtags.

### Posting
- YouTube Shorts, Instagram Reels (aur Story), Facebook Reels, TikTok, Threads, Bluesky, Discord.
- Calendar, fixed time ya gap se posting, roz ki limit.
- **Channel paste karo, daily plan khud bane.**
- YouTube: category, playlist, pehla comment, scheduled publish, A/B title (slow Short ko naya title).
- **Instagram Collab** posts (streamer ke page pe bhi dikhega).
- Hit clips kuch hafton baad naye text ke saath dobara.
- Accounts mein clips baantna (rotation).
- Trending hashtags khud jodna.
- **Song check:** copyright gaane wale clips rok leta hai (AudD key chahiye).
- **Permission:** streamer ne haan kaha ya nahi, aur haan ke bina auto post nahi.
- Review page: swipe karke post ya skip.

### Engagement
- Comments ka AI reply (khud ya aapki approval se).
- Instagram DM keyword rules (comment mein "game" likha to DM jaata hai).
- Telegram se control: post, skip, /status, /pause.

### Daily limit (Settings → Connected apps → Daily limit per page)
- Har page ke liye "Max a day" set karo. YouTube pe default **3 reels/din** hai; isse badha ya ghata sakte ho (0 = koi limit nahi).
- Aapne haath se jo reels daali hain, wo bhi gini jaati hain: YouTube aur Instagram ko app **har 2 ghante** check karta hai.
- App band karke dobara kholo to post karne se **pehle** page check karta hai, phir kaam karta hai.
- Limit poori ho gayi to agli reel agle din usi time pe jaati hai. Date India time ke hisaab se gini jaati hai.

### Autopilot (har creator ki Setup → Autopilot, "Turn on everything" ek click mein)
- **Page ka style seekhna:** har Monday AI aapki best aur sabse kamzor clips dekh ke rules likhta hai; har nayi clip unhe follow karti hai.
- **Hook test:** ek clip, har page pe alag title; 1 din baad jeetne wala style yaad rakhta hai.
- **Prime time pe best clip:** sabse dumdaar clip raat ~9 baje wale slot mein.
- **Viral booster:** 3x chalne wali post turant baaki pages pe, uska lamba "Full moment" version, aur "follow karo" comment.
- **Fast live mode:** live mein 90+ score wali clip turant post.
- **Series:** ek video ki clips "Part 1, 2, 3".
- **Reach-drop alarm:** page ki reach 40% se neeche gire to 3 din 2 post/din, trending hashtags band, aur alert.
- **Copyright guard:** YouTube clip block kare to us creator ki auto-posting turant band.
- **Duplicate guard:** same moment same page pe dobara kabhi nahi.
- **Koi slot khaali nahi:** khaali time pe best unposted clip ya purana hit.
- **English version:** English pages ke liye English subtitles wali copy.
- **Best cover frame**, aur **trending hook formats** (POV, Wait for it 💀, Rate this 1-10).
- **Naye streamers dhoondhna** aur **competitor pages ki viral clips** (Trending page).
- **Telegram channel** pe bhi auto post.

### Kamai (Money page)
- YouTube kamai (28 din), views, watch hours aur Shorts views.
- Monetization progress: abhi 1,000 subs + 4,000 hours ya 10M Shorts views; 1 Feb 2027 se 8,000 hours ya 20M Shorts views.
- Brand deals ka hisaab (kitna mila, kitna baaki, kab due).
- Affiliate links aur unke clicks ki ginti.
- **Link-in-bio page** `/c/aapka-naam`, Instagram bio ke liye.
- Campaign report (CSV).

### Safety aur team
- Email code se login check, two-step sign-in.
- Roz backup, aur har Monday email pe.
- Team: **Manager** (sab kuch) ya **Editor** (sirf clips aur posting).
- Analytics: kaunsa game, platform aur time best chalta hai.
- AI Manager: khud dekhbhaal aur roz report.
- Phone notifications aur phone pe install hone wala app (PWA).

---

## Part 6: Zaroori baatein

- **Permission:** dusre creators ke clips sirf unki ijazat se post karo. App mein ready message hai (creator Setup → Permission).
- Threads, link clicks ki ginti aur phone alerts ke liye app public **https** address pe hona chahiye (cloud server).
- Pehle se connected YouTube ko ek baar dobara Connect karo (kamai dekhne ke liye).
- Music sirf royalty-free daalo (YouTube Audio Library, Pixabay Music).
- Meta/Google apps review hone tak sirf tester accounts connect hote hain, aur YouTube uploads private reh sakte hain.
- Pehli baar ek test post karke check kar lena.
- Password bhool gaye to app ke folder mein chalao:
  `python -m studio.admin owner-login aapka@gmail.com`

## Problem aaye to

| Problem | Hal |
|---|---|
| Facebook connect nahi ho raha | Connected apps → "Facebook Page (easy way, with a token)" use karo |
| Instagram: "Invalid platform app" | Meta App ID ki jagah **Instagram App ID** daalo, ya Meta card se Configuration ID ke saath connect karo |
| YouTube: "not a bot" error | Settings → Connected apps → YouTube links mein cookies daalo |
| Email code nahi aaya | Spam folder dekho; Gmail app password dobara banao |
| Drive full | Settings → Storage se purane videos hatao ya folder badlo |
| Post fail | Calendar/Home pe Retry dabao; Manager khud 3 baar try karta hai |
