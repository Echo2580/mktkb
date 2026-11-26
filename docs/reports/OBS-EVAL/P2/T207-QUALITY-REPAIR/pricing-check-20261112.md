# T207恢复后的官方价格只读核对（2026-11-12）

此记录仅供后续新计划核算；不是计划、GO或产品真实请求证据。未读凭据、未调用模型API、未改账本/预算/GO。

|已冻结provider/model|本次官方页面核对|现有计划单价上界|
|---|---|---|
|DeepSeek / deepseek-flash|缓存未命中输入：空闲1、高峰2元/百万token；输出空闲4、高峰8元/百万token；页面列当前服务版本DeepSeek-V4.1-Flash-1017|输入2、输出8，按高峰上界，不依赖缓存优惠|
|百炼北京 / text-embedding-v4|同步文本输入0.0005元/千token，即0.5元/百万token|0.5元/百万token|
|百炼北京 / gte-rerank-v2|文本输入0.8元/百万token|0.8元/百万token|

依据：[DeepSeek官方模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)、[百炼通用向量同步接口北京价格表](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api/)、[百炼gte-rerank-v2北京价格](https://help.aliyun.com/zh/model-studio/gte-rerank-v2)。本次网页读取确认上述上界未低于所列原价；不依赖免费额度/限时优惠，也不把网页价格当供应商实账或余额。

待代码与确切私有分配完成后，重新计算真实plan的created_utc/plan_sha、各run实际batch/turns/requests与累计余量；公共185请求/1.676032元仅先前形状估计。当前本任务不含OCR重做。若临近真实执行时供应商价格/模型可用性发生变化，应先重新核准，不能沿用失效读数。
