import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  clampSidebarWidth,
  readStoredWidth,
  SIDEBAR_DEFAULT,
  SIDEBAR_MAX,
  SIDEBAR_MIN,
  SIDEBAR_WIDTH_KEY,
  storeWidth,
  widthFromDrag,
  widthFromKey,
} from './sidebarWidth.js'

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial))
  return { getItem: (key) => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), data }
}

test('limits are about 180 to 320 pixels with a 240 default', () => {
  assert.deepEqual([SIDEBAR_MIN, SIDEBAR_DEFAULT, SIDEBAR_MAX], [180, 240, 320])
})

test('widths are clamped to the limits and nonsense falls back to the default', () => {
  assert.equal(clampSidebarWidth(50), SIDEBAR_MIN)
  assert.equal(clampSidebarWidth(900), SIDEBAR_MAX)
  assert.equal(clampSidebarWidth(250.6), 251)
  assert.equal(clampSidebarWidth('abc'), SIDEBAR_DEFAULT)
  assert.equal(clampSidebarWidth(undefined), SIDEBAR_DEFAULT)
})

test('dragging adds the pointer movement to the starting width, within the limits', () => {
  assert.equal(widthFromDrag(240, 240, 290), 290)
  assert.equal(widthFromDrag(240, 240, 100), SIDEBAR_MIN)
  assert.equal(widthFromDrag(240, 240, 900), SIDEBAR_MAX)
  assert.equal(widthFromDrag(200, 200, 200), 200)
})

test('arrow keys step by 16 (48 with Shift), Home and End jump, Enter resets', () => {
  assert.equal(widthFromKey(240, 'ArrowRight'), 256)
  assert.equal(widthFromKey(240, 'ArrowLeft'), 224)
  assert.equal(widthFromKey(240, 'ArrowRight', { shift: true }), 288)
  assert.equal(widthFromKey(310, 'ArrowRight', { shift: true }), SIDEBAR_MAX)
  assert.equal(widthFromKey(190, 'ArrowLeft'), SIDEBAR_MIN)
  assert.equal(widthFromKey(240, 'Home'), SIDEBAR_MIN)
  assert.equal(widthFromKey(240, 'End'), SIDEBAR_MAX)
  assert.equal(widthFromKey(300, 'Enter'), SIDEBAR_DEFAULT)
  assert.equal(widthFromKey(240, 'a'), null)
})

test('the width is stored and read back, and a corrupt stored value is repaired', () => {
  const storage = memoryStorage()
  assert.equal(readStoredWidth(storage), SIDEBAR_DEFAULT)
  storeWidth(280, storage)
  assert.equal(storage.data.get(SIDEBAR_WIDTH_KEY), '280')
  assert.equal(readStoredWidth(storage), 280)
  assert.equal(readStoredWidth(memoryStorage({ [SIDEBAR_WIDTH_KEY]: '5000' })), SIDEBAR_MAX)
  assert.equal(readStoredWidth(memoryStorage({ [SIDEBAR_WIDTH_KEY]: 'junk' })), SIDEBAR_DEFAULT)
})

test('blocked storage never throws', () => {
  const blocked = { getItem: () => { throw new Error('denied') }, setItem: () => { throw new Error('denied') } }
  assert.equal(readStoredWidth(blocked), SIDEBAR_DEFAULT)
  assert.doesNotThrow(() => storeWidth(250, blocked))
  assert.equal(readStoredWidth(null), SIDEBAR_DEFAULT)
})
