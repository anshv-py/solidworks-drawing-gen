# Illustrative STA session pattern (not compiled in this repo yet)

```csharp
// Pattern only. Every SolidWorks member below is annotated with its status in
// references/api-verification.md. Do not ship UNVERIFIED calls.
public sealed class StaDispatcher : IDisposable
{
    private readonly BlockingCollection<Action> _queue = new();
    private readonly Thread _thread;

    public StaDispatcher()
    {
        _thread = new Thread(() => { foreach (var a in _queue.GetConsumingEnumerable()) a(); })
        { IsBackground = true, Name = "sw-sta" };
        _thread.SetApartmentState(ApartmentState.STA);
        _thread.Start();
    }

    public Task<T> Run<T>(Func<T> f)
    {
        var tcs = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
        _queue.Add(() => { try { tcs.SetResult(f()); } catch (Exception e) { tcs.SetException(e); } });
        return tcs.Task;
    }

    public void Dispose() { _queue.CompleteAdding(); _thread.Join(TimeSpan.FromSeconds(30)); }
}

// Usage sketch:
// var view = await sta.Run(() => drawing.CreateDrawViewFromModelView3(partPath, "*Front", xM, yM, 0)); // EXISTS-CONFIRMED
// if (view == null) throw new DrawingOpException("op-002", "CreateDrawViewFromModelView3 returned null");
```
