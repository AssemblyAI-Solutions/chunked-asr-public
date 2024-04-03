import requests
import redis
import os
r = redis.Redis(host='localhost', port=6379, db=0)

WEBHOOK_URL = r.get('ngrok_url').decode() + '/'
ASSEMBLYAI_API_TOKEN = "KEY"

if ASSEMBLYAI_API_TOKEN == "KEY":
    print('Please set your API key in transcribe.py')
    exit()


def read_file(filename, chunk_size=5242880):
    print('Reading file: '+ filename)
    with open(filename, 'rb') as _file:
        while True:
            data = _file.read(chunk_size)
            if not data:
                break
            yield data


def upload_file(filename):
    print('Uploading file: {}'.format(filename))
    headers = {'authorization': ASSEMBLYAI_API_TOKEN}
    response = requests.post('https://api.assemblyai.com/v2/upload',
                            headers=headers,
                            data=read_file(filename))
    url = response.json()['upload_url']
    return url

def create_transcript(url, file_counter, test_id, vendor):
    endpoint = "https://api.assemblyai.com/v2/transcript"

    json = {
        "audio_url": url,
        # "speaker_labels": True,
        "dual_channel": True,
        "webhook_url": WEBHOOK_URL + f"?filenumber={file_counter}&test_id={test_id}&vendor={vendor}",
    }
    headers = {
        "authorization": ASSEMBLYAI_API_TOKEN,
    }
    response = requests.post(endpoint, json=json, headers=headers)
    print("RESPONSE", response)
    id = response.json().get('id')
    print("JOB ID", id)
    r.rpush('job_order', id)
    return response.json()

def get_transcript(id):
    # print('Getting transcript for: {}'.format(id))
    endpoint = "https://api.assemblyai.com/v2/transcript/{}".format(id)
    headers = {'authorization': ASSEMBLYAI_API_TOKEN}
    response = requests.get(endpoint, headers=headers)
    return response.json()
    