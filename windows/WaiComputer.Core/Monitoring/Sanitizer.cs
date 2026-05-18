using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace WaiComputer.Core.Monitoring;

/// <summary>
/// Removes PII from breadcrumb / event payloads before they leave the device.
/// Mirrors the redaction rules in <c>android/.../monitoring/SentryHelper.kt</c>
/// and <c>shared/WaiComputerKit/.../SentryHelper.swift</c> so the three
/// platforms produce identical fingerprints for the same incident.
/// </summary>
public static partial class Sanitizer
{
    private static readonly HashSet<string> SecretKeys = new(StringComparer.OrdinalIgnoreCase)
    {
        "token", "password", "secret", "authorization", "cookie", "access_token", "refresh_token",
    };

    private static readonly HashSet<string> EmailKeys = new(StringComparer.OrdinalIgnoreCase) { "email" };

    private static readonly HashSet<string> FileKeys = new(StringComparer.OrdinalIgnoreCase)
    {
        "filename", "file_name", "title",
    };

    private static readonly HashSet<string> TextKeys = new(StringComparer.OrdinalIgnoreCase)
    {
        "transcript", "query", "question", "text", "content", "body", "detail", "message", "snippet",
    };

    [GeneratedRegex(@"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", RegexOptions.Compiled)]
    private static partial Regex EmailRegex();

    private static readonly Regex UuidRegex = new(
        @"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        RegexOptions.Compiled);

    /// <summary>
    /// Sanitise a single value for the supplied key.
    /// </summary>
    public static object? Sanitize(string key, object? value)
    {
        if (value is null) return null;

        if (SecretKeys.Contains(key)) return "[REDACTED]";

        if (value is string s)
        {
            if (EmailKeys.Contains(key)) return RedactWithFingerprint(s, prefix: "REDACTED");
            if (FileKeys.Contains(key)) return RedactWithFingerprint(s, prefix: "REDACTED");
            if (TextKeys.Contains(key)) return RedactWithLengthAndFingerprint(s);
            return RedactInlineEmails(s);
        }

        if (value is IDictionary<string, object?> dict)
        {
            return SanitizeDictionary(dict);
        }

        if (value is IEnumerable<object?> list && value is not string)
        {
            var sanitised = new List<object?>();
            foreach (var item in list)
            {
                sanitised.Add(item is string si ? RedactInlineEmails(si) : Sanitize(key, item));
            }
            return sanitised;
        }

        return value;
    }

    /// <summary>
    /// Recursively sanitise a dictionary. Returns a new dictionary; the input is
    /// not mutated.
    /// </summary>
    public static IDictionary<string, object?> SanitizeDictionary(IDictionary<string, object?> input)
    {
        var output = new Dictionary<string, object?>(input.Count, StringComparer.Ordinal);
        foreach (var kv in input)
        {
            output[kv.Key] = Sanitize(kv.Key, kv.Value);
        }
        return output;
    }

    /// <summary>
    /// Normalise an URL path for grouping in Sentry (strip UUIDs and numeric IDs).
    /// </summary>
    public static string NormalizePath(string path)
    {
        var stripped = UuidRegex.Replace(path, "{id}");
        return Regex.Replace(stripped, @"/\d+(?=/|$)", "/{id}");
    }

    /// <summary>
    /// Replace any inline email occurrences inside a free-form string.
    /// </summary>
    public static string RedactInlineEmails(string value)
        => EmailRegex().Replace(value, m => RedactWithFingerprint(m.Value, prefix: "REDACTED"));

    public static string Fingerprint(string value, int length = 12)
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(value));
        var sb = new StringBuilder(length);
        for (int i = 0; sb.Length < length && i < bytes.Length; i++)
        {
            sb.Append(bytes[i].ToString("x2", CultureInfo.InvariantCulture));
        }
        return sb.ToString()[..length];
    }

    private static string RedactWithFingerprint(string value, string prefix)
        => $"[{prefix}:{Fingerprint(value)}]";

    private static string RedactWithLengthAndFingerprint(string value)
        => $"[REDACTED:{value.Length}:{Fingerprint(value, length: 6)}]";
}
