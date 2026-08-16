import { createReadStream } from 'node:fs'
import { createServer } from 'node:http'
import { extname, join } from 'node:path'

const photo = { id: '1', name: 'capture.jpg', contract_no: '26MT-03T005', product_type: '法兰', specification: 'WN 4in 300LB', inspection_item: '材质光谱', photographer_name: '林工', captured_at: new Date().toISOString() }
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' }

createServer((request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1:4174')
  if (url.pathname === '/api/v1/dashboard') return json(response, { user: { name: '林' }, pending_task_count: 1, orders: [] })
  if (url.pathname === '/api/v1/photos') return json(response, { photos: [photo], count: 1 })
  if (/^\/api\/v1\/feishu\/photos\/1\/(preview|full)$/.test(url.pathname)) {
    response.writeHead(200, { 'Content-Type': 'image/svg+xml' })
    return response.end('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900"><rect width="1200" height="900" fill="#465660"/><rect x="50" y="50" width="260" height="260" fill="#3370ff"/><rect x="890" y="590" width="260" height="260" fill="#f6a23c"/><text x="430" y="480" fill="white" font-size="64">QC PHOTO</text></svg>')
  }
  const path = join(process.cwd(), 'dist', url.pathname === '/' ? 'index.html' : url.pathname.slice(1))
  const stream = createReadStream(path)
  stream.on('error', () => { response.writeHead(404); response.end() })
  stream.on('open', () => { response.writeHead(200, { 'Content-Type': types[extname(path)] || 'application/octet-stream' }); stream.pipe(response) })
}).listen(4174, '127.0.0.1')

function json(response, value) {
  response.writeHead(200, { 'Content-Type': 'application/json' })
  response.end(JSON.stringify(value))
}
