from openai import OpenAI
# 以下是基础模型及大模型的配置说明，可以替换为其他类似模型
# # 豆包
# base_url = "https://ark.cn-beijing.volces.com/api/v3"
# api_key = ""
# model_name = "doubao-pro-32k-character-241215"

# DeepSeek
base_url = "https://api.deepseek.com"
api_key = "sk-5974b618604c486f912b7b2f6bb7d41c"
# 使用支持联网的模型版本（deepseek-chat 支持联网搜索）
model_name = "deepseek-chat"
# 是否启用联网搜索功能
enable_search = True  # 设置为 True 启用联网搜索，False 则禁用

assert api_key, "您必须配置自己的LLM API秘钥"

llm_client = OpenAI(
    base_url=base_url,
    api_key=api_key,
)


def llm_stream(prompt, use_search=None):
    """
    调用大模型生成流式响应
    
    Args:
        prompt: 用户输入的提示词
        use_search: 是否使用联网搜索，None 则使用全局配置 enable_search
    """
    if use_search is None:
        use_search = enable_search
    
    try:
        # 构建系统提示词，如果启用联网则告知模型可以使用联网功能
        system_content = "你是人工智能助手"
        if use_search:
            system_content += "。你可以使用联网搜索功能来获取最新的实时信息，包括新闻、天气、股票、技术文档等。当用户询问需要最新信息的问题时，请使用联网搜索功能。"
        
        # 准备 API 调用参数
        api_params = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            "stream": True,
        }
        
        # DeepSeek API 的联网功能说明：
        # 1. deepseek-chat 模型本身支持联网搜索功能
        # 2. 当用户询问需要最新信息的问题时，模型会自动使用联网搜索
        # 3. 可以通过系统提示词引导模型使用联网功能
        # 4. 某些情况下可能需要额外的参数，但通常模型会自动判断
        
        stream = llm_client.chat.completions.create(**api_params)
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
