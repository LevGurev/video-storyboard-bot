import telebot
from telebot.types import InputMediaDocument
from telebot.apihelper import ApiTelegramException
import cv2
import os
import time
import yt_dlp

bot = telebot.TeleBot('ВСТАВЬ_СЮДА_СВОЙ_ТОКЕН')


@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        'Привет! Просто пришли мне:\n'
        '- ссылку на ролик (Instagram, YouTube, TikTok), или\n'
        '- видео файлом / как видео (до 20 MB)\n'
        'и я сразу сделаю раскадровку. Команды писать не нужно.'
    )


# ---------- пользователь присылает видео ----------
@bot.message_handler(content_types=['video', 'document'])
def video_save(message):
    # принимаем и документ, и видео
    if message.document:
        file_id = message.document.file_id
    elif message.video:
        file_id = message.video.file_id
    else:
        bot.send_message(message.chat.id, 'Ошибка: пришлите видео файлом или как видео')
        return

    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    with open("video.mp4", "wb") as f:
        f.write(downloaded_file)

    bot.send_message(message.chat.id, 'Обрабатываю весь ролик...')
    storyboard(message)


# ---------- пользователь присылает ссылку ----------
@bot.message_handler(func=lambda m: m.text and m.text.strip().startswith('http'))
def download_link(message):
    url = message.text.strip()
    bot.send_message(message.chat.id, 'Скачиваю...')

    # убираем старый файл, чтобы не остался прошлый ролик
    for f in os.listdir('.'):
        if f.startswith("video."):
            os.remove(f)

    ydl_opts = {
        'outtmpl': 'video.%(ext)s',
        'format': 'mp4/best',
        'quiet': True,
        'overwrites': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if not os.path.exists("video.mp4"):
            for f in os.listdir('.'):
                if f.startswith("video."):
                    os.replace(f, "video.mp4")
    except Exception as e:
        bot.send_message(message.chat.id, 'Не смог скачать: %s' % e)
        return

    bot.send_message(message.chat.id, 'Обрабатываю весь ролик...')
    storyboard(message)


# ---------- раскадровка: топ ключевых сцен ----------
def storyboard(message):
    # сколько кадров максимум отправить (Claude принимает до 20 за раз)
    MAX_FRAMES = 20

    videoCapture = cv2.VideoCapture("video.mp4")

    frames = []
    grays = []
    while True:
        ret, frame = videoCapture.read()
        if not ret:
            break
        frames.append(frame)
        small = cv2.resize(frame, (160, 90))
        grays.append(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))

    if not frames:
        bot.send_message(message.chat.id, 'Не удалось прочитать видео')
        return

    # насколько сильно каждый кадр отличается от предыдущего
    diffs = []
    for i in range(1, len(grays)):
        score = cv2.absdiff(grays[i], grays[i - 1]).mean()
        diffs.append((score, i))

    # берём моменты с самым сильным изменением = смены сцен
    diffs.sort(reverse=True)               # сначала самые большие изменения
    cut_points = [i for _, i in diffs[:MAX_FRAMES - 1]]

    keep = set(cut_points)
    keep.add(0)                            # всегда первый кадр
    keep = sorted(keep)[:MAX_FRAMES]       # на всякий случай не больше лимита

    if not os.path.exists("frames"):
        os.makedirs("frames")

    # сохраняем выбранные кадры на диск
    paths = []
    for i in keep:
        path = "frames/%d.jpg" % i
        cv2.imwrite(path, frames[i])
        paths.append(path)

    # отправляем альбомами по 10 (лимит Telegram), документами для маленького превью
    for batch_start in range(0, len(paths), 10):
        batch = paths[batch_start:batch_start + 10]

        # повторяем при rate-limit (429), пока не отправится
        while True:
            opened = [open(p, 'rb') for p in batch]
            media = [InputMediaDocument(f) for f in opened]
            try:
                bot.send_media_group(message.chat.id, media)
                break
            except ApiTelegramException as e:
                if e.error_code == 429:
                    wait = getattr(e, 'result_json', {}).get('parameters', {}).get('retry_after', 3)
                    time.sleep(wait + 1)
                else:
                    raise
            finally:
                for f in opened:
                    f.close()

        time.sleep(3)  # пауза между альбомами, чтобы не упереться в лимит

    # чистим файлы
    for p in paths:
        os.remove(p)

    bot.send_message(message.chat.id, 'Готово! Отправлено кадров: %d' % len(paths))


bot.polling(none_stop=True)
