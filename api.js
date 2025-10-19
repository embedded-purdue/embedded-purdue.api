 /* exported gapiLoaded, gisLoaded, handleAuthClick, handleSignoutClick */
    const CLIENT_ID = '1058025034355-v633goi4ds5p6km20vo956mdrak4kt4g.apps.googleusercontent.com'
    const API_KEY = process.env.apiKey;

    const DISCOVERY_DOC = 'https://www.googleapis.com/discovery/v1/apis/calendar/v3/rest';
    const SCOPES = 'https://www.googleapis.com/auth/calendar';

    let tokenClient;
    let gapiInited = false;
    let gisInited = false;

    // Hide buttons only after the page loads
    window.onload = () => {
      document.getElementById('authorize_button').style.visibility = 'hidden';
      document.getElementById('signout_button').style.visibility = 'hidden';
    };

    // Attach function to window so it can be called from HTML
    window.gapiLoaded = function() {
      gapi.load('client', initializeGapiClient);
    }

    async function initializeGapiClient() {
      await gapi.client.init({
        apiKey: API_KEY,
        discoveryDocs: [DISCOVERY_DOC],
      });
      gapiInited = true;
      maybeEnableButtons();
    }
    window.gisLoaded = function() {
      tokenClient = google.accounts.oauth2.initTokenClient({
        client_id: CLIENT_ID,
        scope: SCOPES,
        callback: '', // defined later
      });
      gisInited = true;
      maybeEnableButtons();
    }
    

    function maybeEnableButtons() {
      if (gapiInited && gisInited) {
        document.getElementById('authorize_button').style.visibility = 'visible';
      }
    }
    window.handleAuthClick = function() {
      tokenClient.callback = async (resp) => {
        if (resp.error !== undefined) {
          document.getElementById('content').innerText = 'Error: ' + resp.error;
          return;
        }
        document.getElementById('signout_button').style.visibility = 'visible';
        document.getElementById('authorize_button').innerText = 'Refresh';
        await listUpcomingEvents();
      };

      if (gapi.client.getToken() === null) {
        tokenClient.requestAccessToken({ prompt: 'consent' });
      } else {
        tokenClient.requestAccessToken({ prompt: '' });
      }
    }
    
    window.handleSignoutClick = function() {
      const token = gapi.client.getToken();
      if (token !== null) {
        google.accounts.oauth2.revoke(token.access_token);
        gapi.client.setToken('');
        document.getElementById('content').innerText = 'Signed out.';
        document.getElementById('authorize_button').innerText = 'Authorize';
        document.getElementById('signout_button').style.visibility = 'hidden';
      }
    }
    

    async function listUpcomingEvents() {
      let response;
      try {
        response = await gapi.client.calendar.events.list({
          calendarId: 'primary',
          timeMin: new Date().toISOString(),
          showDeleted: false,
          singleEvents: true,
          maxResults: 10,
          orderBy: 'startTime',
        });
      } catch (err) {
        document.getElementById('content').innerText = 'Error: ' + err.message;
        return;
      }

      const events = response.result.items;
      if (!events || events.length === 0) {
        document.getElementById('content').innerText = 'No events found.';
        return;
      }

      const output = events.reduce(
        (str, event) =>
          `${str}${event.summary} (${event.start.dateTime || event.start.date})\n`,
        'Events:\n'
      );
      document.getElementById('content').innerText = output;
    }
    window.makeEvent = async function(){
      const event = {
        'summary': 'Google I/O 2025',
        'location': '800 Howard St., San Francisco, CA 94103',
        'description': 'A chance to hear more about Google\'s developer products.',
        'start': {
          'dateTime': '2025-10-06T09:00:00-04:00',
          'timeZone': 'America/New_York'
        },
        'end': {
          'dateTime': '2025-10-06T11:00:00-04:00',
          'timeZone': 'America/New_York'
        },
        'recurrence': [
          'RRULE:FREQ=DAILY;COUNT=2'
        ],
        'attendees': [
          {'email': 'milo.l.chiu@gmail.com'},
          {'email': 'cchoong992@gmail.com'}
        ],
        'reminders': {
          'useDefault': false,
          'overrides': [
            {'method': 'email', 'minutes': 24 * 60},
            {'method': 'popup', 'minutes': 10}
          ]
        }
      };

      const request = gapi.client.calendar.events.insert({
        'calendarId': 'primary',
        'resource': event
      });

      request.execute(function(event) {
        appendPre('Event created: ' + event.htmlLink);
      });
    }
    
    /*
    // TODO: Add SDKs for Firebase products that you want to use
    // https://firebase.google.com/docs/web/setup#available-libraries

    // Your web app's Firebase configuration
    // For Firebase JS SDK v7.20.0 and later, measurementId is optional
    const firebaseConfig = {
      apiKey: "AIzaSyBoJyo4ilSIvDV-6EBX3WB23JlLhK42P3E",
      authDomain: "digital-op-test.firebaseapp.com",
      projectId: "digital-op-test",
      storageBucket: "digital-op-test.firebasestorage.app",
      messagingSenderId: "1058025034355",
      appId: "1:1058025034355:web:21ce554f5218b7c5d29006",
      measurementId: "G-K50Z68K1Z2"
    };

    // Initialize Firebase
    const app = initializeApp(firebaseConfig);
    const analytics = getAnalytics(app);
    /* exported gapiLoaded, gisLoaded, handleAuthClick, handleSignoutClick */

    