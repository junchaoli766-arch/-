from openai import OpenAI
# 以下是基础模型及大模型的配置说明，可以替换为其他类似模型
# # 豆包
# base_url = "https://ark.cn-beijing.volces.com/api/v3"
# api_key = ""
# model_name = "doubao-pro-32k-character-241215"

# DeepSeek
base_url = "https://api.deepseek.com"
api_key = "sk-5974b618604c486f912b7b2f6bb7d41c"
model_name = "deepseek-chat"

assert api_key, "您必须配置自己的LLM API秘钥"

llm_client = OpenAI(
    base_url=base_url,
    api_key=api_key,
)


def llm_stream(prompt):
    try:
        stream = llm_client.chat.completions.create(
            # 指定您创建的方舟推理接入点 ID，此处已帮您修改为您的推理接入点 ID
            model=model_name,
            messages=[
                {"role": "system", "content": "你是人工智能助手"},
                {"role": "user", "content": prompt},
            ],
            # 响应内容是否流式返回
            stream=True,
        )
        return stream
    except Exception as e:
        # 如果 API 调用失败（如余额不足），返回模拟回答
        print(f"LLM API 调用失败: {e}")
        print("降级使用模拟回答")
        # 返回一个模拟的流式响应
        class MockStream:
            def __init__(self, text):
                self.text = text
                self.index = 0
                self.chunk_size = 5
            
            def __iter__(self):
                return self
            
            def __next__(self):
                if self.index >= len(self.text):
                    raise StopIteration
                
                chunk_text = self.text[self.index:self.index + self.chunk_size]
                self.index += self.chunk_size
                
                class MockChunk:
                    def __init__(self, content):
                        class MockChoice:
                            def __init__(self, content):
                                class MockDelta:
                                    def __init__(self, content):
                                        self.content = content
                                self.delta = MockDelta(content)
                        self.choices = [MockChoice(content)]
                
                return MockChunk(chunk_text)
        
        # 返回模拟回答
        mock_answer = f"抱歉，LLM API 调用失败（可能是余额不足）。您的问题是：{prompt}。这是一个模拟回答，请充值 API 账户后使用真实的大模型服务。"
        return MockStream(mock_answer)
