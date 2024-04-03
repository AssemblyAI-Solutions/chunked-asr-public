# Async Chunking ASR

### How to get started

First, you need to add your AssemblyAI API key in `transcribe.py` and you'll also need a Supabase table set up with the schema found in `app.py`.

The Supabse setup is optional and only used for storing responses. The core chunking logic can be found in `chunked_asr_assembly.py`

1. Install dependencies
```python
pip install -r requirements.txt
```
2. Start [Redis Server](https://redis.io/docs/ui/insight/) on CLI (Current config uses localhost)
```shell
redis-server
```

3. Run ```output.py```, this is responsible for printing transcripts in order
```
python3 output.py
```

4. Run ```app.py```, this is responsible for listening for AssemblyAI Webhooks, sent on transcript completion.
```
python3 app.py
```

5. Run ```chunked_asr_assembly.py```, this is responsible for pulling Audio from URL and chunking into smaller files using Voice Activity Detection (VAD)

```
python3 chunked_asr.py
```


#### *Disclaimer:*

- This is for demo purposes
- Please contact sflamini@assemblyai.com for support!