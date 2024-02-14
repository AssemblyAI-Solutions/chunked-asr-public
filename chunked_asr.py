import requests
import numpy as np
from pydub import AudioSegment
import webrtcvad
import io
import transcribe
import redis
import metrics
import os

r = redis.Redis(host='localhost', port=6379, db=0)

test_id = metrics.start_new_test()

# Constants
url = "https://api.assemblyai-solutions.com/storage/v1/object/public/public-benchmarking/callhome/4093.mp3?t=2024-02-12T16%3A01%3A36.973Z"

pref_chunk_size = 600 #the chunk size you want in seconds
target_chunk_duration_ms = pref_chunk_size * 1000 #converting chunk size to ms
current_chunk_duration_ms = 0 #where we'll store the existing chunk size as we slice audios

# Create a VAD object
vad = webrtcvad.Vad()

# Set its aggressiveness mode
vad.set_mode(1)  # Increased to maximum aggressiveness

# Download the whole file
response = requests.get(url)
# Ensure the request was successful
response.raise_for_status()

# Load the entire audio file
audio = AudioSegment.from_mp3(io.BytesIO(response.content))
print("AUDIO FILE IN SECONDS: ", len(audio) / 1000) 
print("AUDIO FRAME RATE", audio.frame_rate)
# Make sure the frame rate is valid
if audio.frame_rate not in [8000, 16000, 32000, 48000]:
    audio = audio.set_frame_rate(32000)  # Set to 16k Hz as an example

# Try to create audio folder if it doesn't exist
output_dir = "./audio"
try:
    os.mkdir(output_dir, exist_ok=True)
except:
    pass

transcript_ids = []
# monologue_buffer = []
monologue_buffer = AudioSegment.empty()

segment_counter = 0
# Process the audio file in 10 ms chunks
frame_duration_ms = 10

def export_chunk():
    global segment_counter, monologue_buffer, current_chunk_duration_ms, accumulated_silence_ms
    # Only proceed if there's audio to export
    if len(monologue_buffer) > 0:
        segment_counter += 1
        file_name = f"{output_dir}/monologue_{segment_counter}.wav"
        
        # Export the current monologue buffer to an MP3 file
        monologue_buffer.export(file_name, format="wav")
        
        print(f"Exported chunk {segment_counter} to {file_name}")
        
        # Reset for the next chunk
        monologue_buffer = AudioSegment.empty()
        current_chunk_duration_ms = 0
        accumulated_silence_ms = 0
        upload_url = transcribe.upload_file(file_name)
        transcript = transcribe.create_transcript(upload_url, file_name)
        transcript_ids.append(transcript.get('id'))

# Define silence thresholds
MAX_SILENCE_THRESHOLD_MS = 2000  # Maximum silence duration within a chunk
MIN_SILENCE_THRESHOLD_MS = 750  # Minimum silence to finalize a chunk near the target duration

accumulated_silence_ms = 0  # Track silence duration within a chunk

for i in range(0, len(audio), frame_duration_ms):
    chunk = audio[i:i+frame_duration_ms]
    raw_audio = np.array(chunk.get_array_of_samples())
    is_speech = vad.is_speech(raw_audio.tobytes(), sample_rate=chunk.frame_rate)

    if is_speech:
        accumulated_silence_ms = 0  # Reset silence duration when speech is detected
        monologue_buffer = monologue_buffer + chunk
        current_chunk_duration_ms += frame_duration_ms
    else:
        accumulated_silence_ms += frame_duration_ms
        # Only add silence if it's within an ongoing speech segment or if it doesn't exceed a max silence threshold
        if accumulated_silence_ms <= MAX_SILENCE_THRESHOLD_MS:
            monologue_buffer = monologue_buffer + chunk
            current_chunk_duration_ms += frame_duration_ms

    # Check to finalize chunk based on target duration and whether we're in a silence period
    if current_chunk_duration_ms >= target_chunk_duration_ms and accumulated_silence_ms >= MIN_SILENCE_THRESHOLD_MS:
        # Export the chunk if we've hit the target duration and we're currently in a sufficient pause
        export_chunk()
        # Reset for the next chunk
        monologue_buffer = AudioSegment.empty()
        current_chunk_duration_ms = 0
        accumulated_silence_ms = 0

        
# Check and export any remaining audio in monologue_buffer after the loop
if len(monologue_buffer) > 0:
    segment_counter += 1
    file_name = f"{output_dir}/monologue_{segment_counter}.wav"
    monologue_buffer.export(file_name, format="wav")
    print(f"Exported final chunk {segment_counter} to {file_name}")
    upload_url = transcribe.upload_file(file_name)
    transcript = transcribe.create_transcript(upload_url, file_name)
    transcript_ids.append(transcript.get('id'))

    # except Exception as e:
    #     print("Unable to process chunk", i, "Error:", str(e))

# Set last transcript id
# r.set('test_id:' + str(test_id) + ':last_job', transcript_ids[-1])