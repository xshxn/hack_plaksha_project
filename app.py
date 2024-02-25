from pymongo import MongoClient
from datetime import datetime, date, timedelta
import requests
import sys, json, flask, flask_socketio, httplib2, uuid
from flask import Response, request, render_template, session, redirect, Flask
from flask_session import Session
from flask_socketio import SocketIO
from apiclient import discovery
from oauth2client import client
from googleapiclient import sample_tools
from rfc3339 import rfc3339
from dateutil import parser
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.errors import HttpError
client = MongoClient("localhost", 27017)

db = client.hackdb

users = db.users
tasks = db.tasks

SCOPES=['https://www.googleapis.com/auth/calendar', 
        'https://www.googleapis.com/auth/userinfo.profile', 
        'https://www.googleapis.com/auth/userinfo.email', 
        'openid'    ]

app = Flask(__name__)
socketio = SocketIO(app)

app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

def get_credentials():
    if 'credentials' in session:
        credentials = Credentials.from_authorized_user_info(json.loads(session['credentials']))
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        return credentials

@app.route('/')
def index():
    credentials = get_credentials()
    if credentials is None:
        return redirect("/oauth2callback")
    else:
       return render_template("homepage.html", name = flask.session["user_name"])

@app.route('/calendar_events')
def calendar_events():
    credentials = get_credentials()
    if credentials is None:
        return redirect('/oauth2callback')

    service = build('calendar', 'v3', credentials=credentials)
    try:
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)

        timeMin = datetime.combine(today, datetime.min.time()).isoformat() + 'Z'
        timeMax = datetime.combine(tomorrow, datetime.max.time()).isoformat() + 'Z'
        events_result = service.events().list(timeMin = timeMin, timeMax = timeMax, calendarId='primary', maxResults=250, singleEvents=True, orderBy='startTime').execute()
        events = events_result.get('items', [])
        formatted_events = []
        for event in events:
            formatted_event = {
                'summary': event['summary'],
                'start_time': datetime.strptime(event['start']['dateTime'], "%Y-%m-%dT%H:%M:%S%z").strftime('%Y-%m-%d %H:%M:%S'),
                'end_time': datetime.strptime(event['end']['dateTime'], "%Y-%m-%dT%H:%M:%S%z").strftime('%Y-%m-%d %H:%M:%S')
            }
            formatted_events.append(formatted_event)
        num_events = len(formatted_events)
        print(num_events)
        return render_template("calendar_events.html", events=formatted_events, num_events=num_events)
    except HttpError as error:
        return f'An error occurred: {error}'

#Begin oauth callback route
@app.route('/oauth2callback')
def oauth2callback():
  flow = InstalledAppFlow.from_client_secrets_file(
      'client_secrets.json',
      scopes=SCOPES,
      redirect_uri=flask.url_for('oauth2callback', _external=True))
  if 'code' not in flask.request.args:
    auth_uri, _ = flow.authorization_url(prompt = 'consent')
    return flask.redirect(auth_uri)
  else:
    auth_code = flask.request.args.get('code')
    flow.fetch_token(code=auth_code)
    credentials = flow.credentials

    user_info_url = 'https://www.googleapis.com/oauth2/v2/userinfo' 
    user_info_response = requests.get(user_info_url, headers={'Authorization': f'Bearer {credentials.token}'})
    user_info = user_info_response.json()
    flask.session['user_name'] = user_info.get('name', 'Unknown')
    flask.session['user_email'] = user_info.get('email', 'Unknown') 
    flask.session['credentials'] = credentials.to_json()
    count = 0

    for person in users.find():
        if person["name"] == session.get("user_name"):
            count = count + 1
    if count == 0:
        users.insert_one({"name": session.get("user_name"), "email": session.get("user_email")})


    return redirect("/")
    #return render_template("logged.html", logged = datetime.now())
  
@app.route("/add_event", methods = ["GET", "POST"])
def add_event():
    if request.method == "POST":
        credentials = get_credentials()
        if credentials is None:
            return redirect('/oauth2callback')
        service = build('calendar', 'v3', credentials=credentials)
        try:
            
            summary = request.form.get("task")
            priority = request.form.get("priority")
            dif = request.form.get("dif")
            daysleft = request.form.get("dayslft")
            tasks.insert_one({"name": summary, "priority": priority, "difficulty": dif, "daysleft": daysleft})
            return redirect("/add_event")
        except:
            print("Error")
            return redirect("/add_event")
    else:
        return render_template("add_event.html")

@app.route("/optimize", methods = ["GET", "POST"])
def optimize():
    if request.method == "POST":
        duration_study = []
        avltime = request.form.get("avltime")
        weights = []
        tasksleft = []
        priorities = []
        difficulties = []
        days = []
        for task in tasks.find():
            tasksleft.append(task["name"])
        for task in tasks.find():
            priorities.append(task["priority"])
        for task in tasks.find():
            difficulties.append(task["difficulty"])
        for task in tasks.find():
            days.append(task["daysleft"])
            weights.append(0)
        
        for i in range(len(days)):
            days[i] = 30 - int(days[i])
        for i in range(len(weights)):
            x = int(priorities[i])+2*(int(days[i])) + int(difficulties[i])
            weight = x/80
            weights[i] = weight
        for i in range(len(weights)):
            x = (weights[i]*int(avltime))/sum(weights)
            duration_study.append(int((x)))
        for i in range(len(duration_study)):
            x = duration_study[i]%5
            duration_study[i] = duration_study[i]-x
        print(tasksleft)
        print(duration_study)
        tasks.delete_many({})
        return render_template("optimized.html", tasks = tasksleft, times = duration_study)
    else:
        return render_template("optimize.html")

@app.route("/add_calendar", methods = ["GET", "POST"])
def add_calendar():
    if request.method == "POST":
        credentials = get_credentials()
        if credentials is None:
            return redirect('/oauth2callback')
        service = build('calendar', 'v3', credentials=credentials)
        try:
            task1 = request.form.get("task1")
            start = request.form.get("start")
            starttime = request.form.get("starttime")
            end = request.form.get("end")
            endtime = request.form.get("endtime")

            start_datetime = datetime.strptime(f"{start} {starttime}", "%Y-%m-%d %H:%M")
            end_datetime = datetime.strptime(f"{end} {endtime}", "%Y-%m-%d %H:%M")
            event = {
                'summary': task1,
                'location': "",
                'description': "",
                'start':{
                    'dateTime': start_datetime.isoformat() ,
                    'timeZone': 'Asia/Kolkata',
                },
                'end':{
                    'dateTime': end_datetime.isoformat() ,
                    'timeZone': 'Asia/Kolkata',
                },
                'reminders':{
                    'useDefault':True,
                },

            }

            event = service.events().insert(calendarId='primary', body=event).execute()
            return redirect("/")
        except:
            return redirect("/add_calendar")
        return
    else:
        return render_template("add_calendar.html")


@app.route("/logout")
def logout():                                                                                   
   session.clear()
   return redirect("/")

@app.route("/cup")
def cup():
    credentials = get_credentials()
    if credentials is None:
        return redirect('/oauth2callback')

    service = build('calendar', 'v3', credentials=credentials)
    try:
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)

        timeMin = datetime.combine(today, datetime.min.time()).isoformat() + 'Z'
        timeMax = datetime.combine(tomorrow, datetime.max.time()).isoformat() + 'Z'
        events_result = service.events().list(timeMin = timeMin, timeMax = timeMax, calendarId='primary', maxResults=250, singleEvents=True, orderBy='startTime').execute()
        events = events_result.get('items', [])
        formatted_events = []
        for event in events:
            formatted_event = {
                'summary': event['summary'],
                'start_time': datetime.strptime(event['start']['dateTime'], "%Y-%m-%dT%H:%M:%S%z").strftime('%Y-%m-%d %H:%M:%S'),
                'end_time': datetime.strptime(event['end']['dateTime'], "%Y-%m-%dT%H:%M:%S%z").strftime('%Y-%m-%d %H:%M:%S')
            }
            formatted_events.append(formatted_event)
        num_events = len(formatted_events)
        return render_template("cup.html", num_events=num_events)
    except:
        return redirect("/")



if __name__ == '__main__':
    app.secret_key = str(uuid.uuid4())
    socketio.run(
    app,
    host='localhost',
    port=int(8080)
    )

