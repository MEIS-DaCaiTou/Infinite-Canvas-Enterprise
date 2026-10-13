/* Run platform API requests in its logged-in tab. No token extraction or CORS bypass. */
window.CanvasPlatformClient = {
  async request(base, path, options = {}) {
    if(!['/api/config', '/api/local-assets/import-urls'].includes(path)) throw new Error('不支持的平台请求');
    const origin = new URL(base).origin;
    const tabs = await chrome.tabs.query({url: `${origin}/*`});
    const tab = tabs.find(t => t.id && new URL(t.url).origin === origin);
    if(!tab) {
      await chrome.tabs.create({url: `${origin}/`});
      throw new Error('已打开平台页面，请先登录平台，再返回插件点击连接。');
    }
    const results = await chrome.scripting.executeScript({
      target:{tabId:tab.id},
      func:async (expectedOrigin, apiPath, init) => {
        if(location.origin !== expectedOrigin) return {ok:false, status:0, text:'平台页面地址已变化，请重新连接'};
        const response = await fetch(apiPath, {...init, credentials:'same-origin'});
        return {ok:response.ok, status:response.status, text:await response.text()};
      },
      args:[origin, path, options],
    });
    const result = results[0]?.result;
    if(!result) throw new Error('无法读取平台页面，请确认页面加载完成后重新连接');
    if(result.status === 401) throw new Error('平台尚未登录或登录已过期，请在平台页面登录后重新连接。');
    if(!result.ok) throw new Error(`平台请求失败 HTTP ${result.status}：${result.text.slice(0,300)}`);
    try { return JSON.parse(result.text); }
    catch (_) { throw new Error('平台未返回 JSON，请确认使用企业入口地址'); }
  },
};
