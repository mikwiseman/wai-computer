using System.Globalization;
using System.Net;
using System.Net.Http;
using Microsoft.Extensions.Caching.Memory;
using Sentry;
using WaiComputer.Core.Api;

namespace WaiComputer.Core.Monitoring;

/// <summary>
/// Thin opinionated wrapper around the Sentry .NET SDK. Adds:
/// <list type="bullet">
///   <item>5-minute fingerprint-keyed dedup to keep volume sane</item>
///   <item>HTTP/network failure categorisation matching the Mac+Android helpers</item>
///   <item>PII sanitisation on every breadcrumb / event</item>
/// </list>
/// </summary>
public sealed class SentryHelper : IDisposable
{
    private readonly IDisposable? _sentry;
    private readonly MemoryCache _seen = new(new MemoryCacheOptions { SizeLimit = 1024 });
    private static readonly TimeSpan DedupWindow = TimeSpan.FromMinutes(5);

    public SentryHelper(string dsn, bool debug = false, double tracesSampleRate = 0.1, double profilesSampleRate = 0.1)
    {
        _sentry = SentrySdk.Init(o =>
        {
            o.Dsn = dsn;
            o.Debug = debug;
            o.TracesSampleRate = tracesSampleRate;
            o.ProfilesSampleRate = profilesSampleRate;
            o.AttachStacktrace = true;
            o.AutoSessionTracking = true;
            o.SendDefaultPii = false;
            o.Environment = debug ? "development" : "production";
            o.SetBeforeSend((evt, _) =>
            {
                evt.SetExtra("sanitized", "true");
                return evt;
            });
            o.SetBeforeBreadcrumb((b, _) =>
            {
                if (b is null) return b;
                if (b.Data is not null)
                {
                    var sanitised = Sanitizer.SanitizeDictionary(
                        b.Data.ToDictionary(kv => kv.Key, kv => (object?)kv.Value));
                    foreach (var k in b.Data.Keys.ToList())
                    {
                        if (sanitised.TryGetValue(k, out var v))
                        {
                            b.Data[k] = v?.ToString() ?? string.Empty;
                        }
                    }
                }
                return b;
            });
        });
    }

    public void SetUser(string id) => SentrySdk.ConfigureScope(s => s.User = new SentryUser { Id = id });

    public void ClearUser() => SentrySdk.ConfigureScope(s => s.User = null);

    public void AddBreadcrumb(string category, string message, BreadcrumbLevel level = BreadcrumbLevel.Info, IDictionary<string, string>? data = null)
    {
        SentrySdk.AddBreadcrumb(message, category, level: ToSentryLevel(level), data: data);
    }

    public void CaptureRequestFailure(HttpMethod method, string path, int? statusCode, string errorKind, Exception? exception)
    {
        var normalisedPath = Sanitizer.NormalizePath(path);
        var fingerprint = $"request:{method.Method}:{normalisedPath}:{errorKind}";

        if (statusCode == (int)HttpStatusCode.Unauthorized)
        {
            AddBreadcrumb("api", $"{method.Method} {normalisedPath} unauthorized", BreadcrumbLevel.Info);
            return;
        }

        var crumbData = new Dictionary<string, string>
        {
            ["method"] = method.Method,
            ["path"] = normalisedPath,
            ["error_kind"] = errorKind,
            ["status"] = statusCode?.ToString(CultureInfo.InvariantCulture) ?? "n/a",
        };

        if (statusCode is < 500 and >= 100)
        {
            AddBreadcrumb("api", $"{method.Method} {normalisedPath} → {statusCode}",
                statusCode >= 400 ? BreadcrumbLevel.Warning : BreadcrumbLevel.Info, crumbData);
            return;
        }

        if (!_seen.TryGetValue(fingerprint, out _))
        {
            _seen.Set(fingerprint, true, new MemoryCacheEntryOptions
            {
                AbsoluteExpirationRelativeToNow = DedupWindow,
                Size = 1,
            });

            SentrySdk.CaptureEvent(new SentryEvent(exception)
            {
                Level = SentryLevel.Error,
                Fingerprint = new[] { fingerprint },
                Message = $"{method.Method} {normalisedPath} failed ({errorKind})",
            });
        }
        else
        {
            AddBreadcrumb("api", $"{method.Method} {normalisedPath} failed (dedup)", BreadcrumbLevel.Warning, crumbData);
        }
    }

    public void CaptureException(Exception ex, string action)
    {
        SentrySdk.CaptureEvent(new SentryEvent(ex)
        {
            Level = SentryLevel.Error,
            Fingerprint = new[] { $"action:{action}" },
        });
    }

    private static SentryLevel ToSentryLevel(BreadcrumbLevel level) => level switch
    {
        BreadcrumbLevel.Debug => SentryLevel.Debug,
        BreadcrumbLevel.Info => SentryLevel.Info,
        BreadcrumbLevel.Warning => SentryLevel.Warning,
        BreadcrumbLevel.Error => SentryLevel.Error,
        _ => SentryLevel.Info,
    };

    public void Dispose() => _sentry?.Dispose();
}

public enum BreadcrumbLevel { Debug, Info, Warning, Error }
