from flask import Flask, render_template, request, jsonify, redirect, session, url_for
from openai import OpenAI
import os
import json
import warnings
import ffmpeg as ff
import pyrebase
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip
import smtplib
from dotenv import load_dotenv
from io import BytesIO
import requests
import tempfile
import secrets
load_dotenv()
# environment variables

OPENAI_API_KEY = os.getenv("API_KEY")
EMAIL_ADDR = os.getenv("EMAIL_ADDR")
PASSWORD = os.getenv("PASSWORD")
SECRET_KEY = os.getenv("SECRET_KEY")

warnings.filterwarnings("ignore", category=DeprecationWarning)

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
config = {
        "apiKey": "AIzaSyBhJdrBJSTB6HUf3oFM2ApDqzGD6puwAYs",
        "authDomain": "medi-6d00f.firebaseapp.com",
        "projectId": "medi-6d00f",
        "storageBucket": "medi-6d00f.appspot.com",
        "messagingSenderId": "114277222290",
        "appId": "1:114277222290:web:3820df5ffe0bf52148634b",
        "measurementId": "G-C5R7BT9KBZ",
        "databaseURL": "https://medi-6d00f-default-rtdb.firebaseio.com/"
    };

firebase = pyrebase.initialize_app(config)
auth = firebase.auth()
db = firebase.database()
storage = firebase.storage()
app.secret_key = 'secret'


@app.route('/register', methods=['POST', 'GET'])
def sign_up():
    if request.method == 'POST':
        fname = request.form.get('fname')
        session['fname'] = fname
        email = request.form.get('sign-up-email')
        password = request.form.get('sign-up-password')
        user_data = {"email": email, "name": fname, "links": []}
        user = auth.create_user_with_email_and_password(email, password)
        session['user_id'] = user['localId']
        session['email'] = email
        db.child("users").child(user['localId']).set(user_data)
    return render_template('register.html')


@app.route('/dashboard')
def get_all_posts():
    if 'user_id' in session:
        user_id = session['user_id']
        user_data = db.child("users").child(user_id).get().val()
        fname = user_data.get('name', None)
    else:
        fname = "User"
    return render_template('dashboard.html', fname=fname)

@app.route('/meditationgenerator')
def charts():
    user_id = session.get('user_id', None)
    email = session.get('email', None)
    return render_template('meditationgen.html',  user_id=user_id, email=email)

@app.route('/meditation', methods=["POST"])
def generate_audio():
    description = request.form["description"]
    duration = int(request.form["duration"])
    theme = request.form["theme"].strip().title()
    voice = request.form["voice"]
    voice = voice.strip().title()

    client = OpenAI(api_key=OPENAI_API_KEY)

    if voice == "Female":
        voice = "nova"
    else:
        voice = "onyx"

    words_per_minute = 175
    max_words = int(words_per_minute * (duration / 60))

    system_prompt = (f"You're a guided Mediation expert, users express the problems they're having, \
    and you respond in json format with the {{'title': title, 'text': script', 'suggestion': suggestions}} dict in one whole blob.\
    The vocals are spaced out over {duration} second duration, the final script \
    should fill the entire {duration} duration also say.Do some breathing exercises during \
    the session and make sure the script has specific lines about \
    the problem faced by the user from description. \
    includes specific lines about the problem. \
    Make sure that the script has a key of 'text'. Finally, for the suggestions section, provide suggestions on what the \
    user can do to help themselves overcome this problem (1 sentence max). Do not speak quickly.")

    script_response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": f"{system_prompt}"},
            {"role": "user", "content": f"{description} in {duration}"}
        ]
    )
    response_json = json.loads(script_response.choices[0].message.content)
    print(response_json)
    title = response_json["title"]
    suggestion = response_json["suggestion"]

    audio_file_number = 0
    audio_files = []
    audio_inputs = []

    audio_response = client.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=response_json["text"] + response_json["suggestion"],
    )

    audio_buffer = BytesIO(audio_response.content)

    # Upload the audio directly to Firebase Storage
    storage.child(f"initial_audios/{title}_initial_audio.mp3").put(audio_buffer.getvalue())
    initial_audio_url = storage.child(f"initial_audios/{title}_initial_audio.mp3").get_url(None)
    print(initial_audio_url)

    # Download the initial audio for processing
    response = requests.get(initial_audio_url)
    initial_audio_path = f'/tmp/{title}_initial_audio.mp3'
    with open(initial_audio_path, 'wb') as f:
        f.write(response.content)

    general_music_path = f'/tmp/{theme}.mp3'
    storage.child('General.mp3').download(general_music_path, general_music_path)

    background_music = ff.input(general_music_path)
    background_music = background_music.filter('volume', 0.3)

    speech_input = ff.input(initial_audio_path)
    mixed_audio = ff.filter([speech_input, background_music], 'amix')
    final_audio = ff.output(mixed_audio, 'combined_output6.mp3', t=duration, y=None)
    ff.run(final_audio)

    audio = AudioFileClip('combined_output6.mp3')
    audio = audio.audio_fadeout(3)

    video_path = f'{theme}.mp4'
    storage.child(f"{theme}.mp4").download(video_path, video_path)

    clip1 = VideoFileClip(video_path).subclip(0, duration)

    clip1.audio = CompositeAudioClip([audio])

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_video_file:
        temp_video_path = temp_video_file.name

        # Write the video to the temporary file
    clip1.write_videofile(temp_video_path, audio_codec='aac')

    # Upload the audio and video to Firebase Storage
    audio_blob = storage.child(f"audios/{title}_audio.mp3").put("combined_output6.mp3")
    audio_url = storage.child(f"audios/{title}_audio.mp3").get_url(None)

    video_blob = storage.child(f"videos/{title}_video.mp4").put(temp_video_path)
    video_url = storage.child(f"videos/{title}_video.mp4").get_url(None)

    # Clean up the temporary file
    os.unlink(temp_video_path)

    user_id = session['user_id']
    db.child("users").child(user_id).child("links").push({
        "name": title,
        "audio": audio_url,
        "video": video_url,
        "suggestion": suggestion
    })

    return jsonify({
        "success": True,
        "audio_link": audio_url,
        "video_link": video_url
    })


@app.route('/generatedcontent', methods=['GET', 'POST'])
def list_audios():
    if 'user_id' in session:
        user_id = session['user_id']
        email = session['email']
        user_data = db.child("users").child(user_id).get().val()
        if user_data and 'links' in user_data:
            links = user_data['links']
        else:
            links = {}

        return render_template('generatedcontent.html', email=email, links=links)
    else:
        return redirect(url_for('login'))


@app.route('/send_email', methods=['POST'])
def send_email():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'User not logged in'})

    user_id = session['user_id']
    user_data = db.child("users").child(user_id).get().val()
    recipient_email = user_data.get('email')
    links = user_data.get('links', {})

    latest_link = list(links.values())[-1]
    audio_link = latest_link.get('audio')
    video_link = latest_link.get('video')
    meditation_name = latest_link.get('name')

    text = f"""Here are your meditation links for '{meditation_name}':
    Audio: {audio_link}
    Video: {video_link}"""

    my_email = EMAIL_ADDR
    password = PASSWORD

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as connection:
            connection.login(my_email, password)
            connection.sendmail(
                from_addr=my_email,
                to_addrs=recipient_email,
                msg=f"Subject:{meditation_name}\n\n{text}"
            )
        return jsonify({'success': True, 'message': 'Email sent successfully'})
    except:
        return jsonify({'success': False, 'message': 'Failed to send email'})

@app.route('/login', methods=['POST', 'GET'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        try:
            user = auth.sign_in_with_email_and_password(email, password)
            session['user_id'] = user['localId']
            session['email'] = email
            user_data = db.child("users").child(user['localId']).get().val()
            session["fname"] = user_data["fname"]
            return redirect(url_for('index'))
        except:
            return redirect(url_for('login'))

    fname = session.get('fname', None)
    return render_template('login.html', fname=fname)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('email', None)
    session.pop('fname', None)
    return redirect(url_for('home'))

@app.route('/')
def home():
    return render_template('home.html')



if __name__ == "__main__":
    app.run(debug=True, port=2223)
