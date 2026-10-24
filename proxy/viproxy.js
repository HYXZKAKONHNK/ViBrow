addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})

async function handleRequest(request) {
  const urlObj = new URL(request.url)
  let urlStr = urlObj.searchParams.get('url')

  // Автоматический рендеринг картинок и стилей сайтов внутри iframe
  if (!urlStr) {
    const referer = request.headers.get('Referer')
    if (referer && referer.includes(urlObj.hostname)) {
      try {
        const refUrl = new URL(referer)
        const actualTarget = refUrl.searchParams.get('url')
        if (actualTarget) {
          const originUrl = new URL(actualTarget)
          urlStr = originUrl.origin + urlObj.pathname + urlObj.search
        }
      } catch (e) {}
    }
  }

  if (!urlStr) {
    return new Response('ViBrow Ultra-Proxy v5.1 is Active!', {
      status: 200,
      headers: { 'Content-Type': 'text/plain; charset=utf-8', 'Access-Control-Allow-Origin': '*' }
    })
  }

  try {
    // 🛡️ 1. МАСКИРОВКА IP И ДЕПАКЕТИЗАЦИЯ
    const randomIP = `${Math.floor(Math.random() * 140) + 20}.${Math.floor(Math.random() * 200)}.${Math.floor(Math.random() * 200)}.${Math.floor(Math.random() * 240) + 10}`
    
    let secureHeaders = new Headers()
    
    secureHeaders.set('X-Forwarded-For', randomIP)
    secureHeaders.set('X-Real-IP', randomIP)
    secureHeaders.set('True-Client-IP', randomIP)
    secureHeaders.set('Client-IP', randomIP)
    
    // 🛡️ 2. МАСКИРОВКА ЦИФРОВОГО ОТПЕЧАТКА
    secureHeaders.set('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
    secureHeaders.set('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8')
    secureHeaders.set('Accept-Language', 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7')
    secureHeaders.set('Cache-Control', 'max-age=0')
    secureHeaders.set('Sec-Ch-Ua', '"Chromium";v="124", "Google Chrome";v="124"')
    secureHeaders.set('Sec-Ch-Ua-Platform', '"Windows"')
    secureHeaders.set('Sec-Fetch-Dest', 'document')
    secureHeaders.set('Sec-Fetch-Mode', 'navigate')
    secureHeaders.set('Sec-Fetch-Site', 'none')

    // Пробрасываем оригинальный метод запроса (GET, POST и т.д.)
    const fetchOptions = {
      method: request.method,
      headers: secureHeaders,
      redirect: 'follow'
    }

    // Если это POST/PUT запрос с телом, передаем его дальше
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      fetchOptions.body = request.body
    }

    let response = await fetch(urlStr, fetchOptions)

    // 🛡️ 3. ОБРАБОТКА ЗАГОЛОВКОВ И СТИРАНИЕ CORS
    let newHeaders = new Headers(response.headers)
    newHeaders.set('Access-Control-Allow-Origin', '*')
    newHeaders.set('Access-Control-Allow-Methods', 'GET, HEAD, POST, OPTIONS, PUT, DELETE')
    newHeaders.set('Access-Control-Allow-Headers', '*')
    
    newHeaders.delete('X-Frame-Options')
    newHeaders.delete('Content-Security-Policy')
    newHeaders.delete('X-Content-Type-Options')

    const contentType = newHeaders.get('Content-Type') || ''

    // Если это HTML, безопасно правим текст
    if (contentType.includes('text/html')) {
      let bodyText = await response.text()
      const targetOrigin = new URL(urlStr).origin
      bodyText = bodyText.replace(/(src|href)=["']\/(?!\/)/g, `$1="${urlObj.origin}/?url=${targetOrigin}/`)
      
      return new Response(bodyText, { 
        status: response.status, 
        statusText: response.statusText, 
        headers: newHeaders 
      })
    }

    // Для ВСЕХ остальных файлов (скрипты, стили, картинки) отдаем поток как есть
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: newHeaders
    })

  } catch (err) {
    return new Response('Secure Proxy Error: ' + err.message, {
      status: 500,
      headers: { 'Access-Control-Allow-Origin': '*', 'Content-Type': 'text/plain; charset=utf-8' }
    })
  }
}