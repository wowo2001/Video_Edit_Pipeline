OUTPUT_SCHEMA = """
JSON 输出格式

{
  "hook": {
    "narrative": {
      "content": "开场钩子旁白"
    },
    "clip": [12, 13]
  },

  "clips": [
    {
      "place": 1,
      "narrative": {
        "content": "剧情旁白"
      },
      "clip": [45, 46, 47]
    },
    {
      "place": 2,
      "narrative": {
        "content": "剧情旁白"
      },
      "clip": [78]
    }
  ]
}
"""