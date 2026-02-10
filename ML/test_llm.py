from llm_enrich import enrich_product_name
from llm_enrich import enrich_product_name, client, LLM_PROMPT_TEMPLATE

result = enrich_product_name("Мужские джинсы Levis 501 Original Fit, синие")
print("✅ Результат:", result)

name = "Мужские джинсы Levis 501 Original Fit, синие"
prompt = LLM_PROMPT_TEMPLATE.format(product_name=name)

response = client.chat.completions.create(
    messages=[
        {"role": "system", "content": "Ты всегда отвечаешь строго в формате JSON, без пояснений и без дополнительного текста."},
        {"role": "user", "content": prompt}
    ],
    model="Meta-Llama-3-70B-Instruct-GPTQ",
    temperature=0.0,
    max_tokens=250,
    stream=False
)

raw_output = response.choices[0].message.content
print("🔍 Сырой ответ от LLM:")
print(repr(raw_output))  # покажет всё, включая \n и скрытые символы