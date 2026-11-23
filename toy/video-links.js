(() => {
  const sdk = window.toy;
  if (typeof sdk?.navigate !== 'function') return;

  let canNavigate = true;
  if (typeof sdk.isSupport === 'function'){
    sdk.isSupport('navigate').then(supported => { canNavigate = supported; }, () => {});
  }

  document.getElementById('matchTable').addEventListener('click', async event => {
    if (!canNavigate || !event.isTrusted || event.defaultPrevented || event.button !== 0
      || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;

    const link = event.target.closest('a[data-bvid]');
    if (!link) return;

    event.preventDefault();
    try {
      await sdk.navigate({type:'video', id:link.dataset.bvid});
    } catch {
      // 站内跳转失败时，交回给链接原有的浏览器打开方式。
      link.click();
    }
  });
})();
