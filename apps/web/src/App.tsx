function App() {
  return (
    <main className="shell">
      <section className="card" aria-labelledby="title">
        <p className="eyebrow">P0 工程骨架</p>
        <h1 id="title">AI 教学平台</h1>
        <p>前端入口已就绪。后续步骤将接入登录、班级、作业和批改流程。</p>
        <div className="status" role="status">
          API 地址：<code>/healthz</code>
        </div>
      </section>
    </main>
  );
}

export default App;

