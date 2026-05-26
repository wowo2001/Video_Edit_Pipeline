OUTPUT_SCHEMA = """
JSON 输出格式：

{
  "hook": {
    "narrative": {
      "content": "开场钩子旁白",
      "length": "00:00:03,000"
    },
    "clip": {
      "content": "对应字幕内容",
      "start": "00:00:00,000",
      "end": "00:00:05,000"
    }
  },
  "clips": [
    {
      "place": 1,
      "narrative": {
        "content": "剧情旁白",
        "length": "00:00:03,000"
      },
      "clip": {
        "content": "对应字幕内容",
        "start": "00:00:05,000",
        "end": "00:00:12,000"
      }
    },
    {
      "place": 2,
      "narrative": {
        "content": "剧情旁白",
        "length": "00:00:04,000"
      },
      "clip": {
        "content": "对应字幕内容",
        "start": "00:00:12,000",
        "end": "00:00:20,000"
      }
    }
  ]
}
"""