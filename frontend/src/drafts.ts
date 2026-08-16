export type PhotoDraft = {
  id: string
  contractNo: string
  taskId: string
  inspectionItem: string
  capturedAt: string
  image: Blob
  createdAt: number
}

const DATABASE = 'qc-photo-drafts'
const STORE = 'photos'
const RETENTION_MS = 24 * 60 * 60 * 1000

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1)
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: 'id' })
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('无法打开本地草稿库'))
  })
}

async function transaction<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await database()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode)
    const request = action(tx.objectStore(STORE))
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('本地草稿操作失败'))
    tx.oncomplete = () => db.close()
    tx.onerror = () => reject(tx.error || new Error('本地草稿操作失败'))
  })
}

export async function cleanExpiredDrafts(now = Date.now()): Promise<void> {
  const db = await database()
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    const store = tx.objectStore(STORE)
    const cursor = store.openCursor()
    cursor.onsuccess = () => {
      const current = cursor.result
      if (!current) return
      if ((current.value as PhotoDraft).createdAt < now - RETENTION_MS) current.delete()
      current.continue()
    }
    tx.oncomplete = () => { db.close(); resolve() }
    tx.onerror = () => reject(tx.error || new Error('清理过期草稿失败'))
  })
}

export async function saveDraft(draft: PhotoDraft): Promise<void> {
  await transaction('readwrite', store => store.put(draft))
}

export async function draftsForContract(contractNo: string): Promise<PhotoDraft[]> {
  const all = await transaction<PhotoDraft[]>('readonly', store => store.getAll())
  return all.filter(draft => draft.contractNo === contractNo).sort((a, b) => a.createdAt - b.createdAt)
}

export async function removeDraft(id: string): Promise<void> {
  await transaction('readwrite', store => store.delete(id))
}

export async function removeDrafts(ids: string[]): Promise<void> {
  const db = await database()
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    const store = tx.objectStore(STORE)
    ids.forEach(id => store.delete(id))
    tx.oncomplete = () => { db.close(); resolve() }
    tx.onerror = () => reject(tx.error || new Error('删除已提交草稿失败'))
  })
}
