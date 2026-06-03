using System.Security.AccessControl;
using System.Security.Principal;
using WaiComputer.Core.Auth;

namespace WaiComputer.Native.Platform;

/// <summary>
/// Listens for <see cref="SessionStore.AclApplied"/> and trims the file ACL to
/// the current user only — equivalent to <c>chmod 0600</c> on Unix. Wires up
/// once at app startup.
/// </summary>
public static class WindowsAclHelper
{
    private static bool _attached;

    public static void Attach()
    {
        if (_attached) return;
        _attached = true;
        SessionStore.AclApplied += TrimToCurrentUser;
    }

    private static void TrimToCurrentUser(string path)
    {
        if (!File.Exists(path)) return;

        var info = new FileInfo(path);
        var security = info.GetAccessControl();

        // Disable inheritance, copy existing rules so we can strip them.
        security.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
        foreach (FileSystemAccessRule rule in security.GetAccessRules(true, true, typeof(NTAccount)))
        {
            security.RemoveAccessRule(rule);
        }

        var currentUser = WindowsIdentity.GetCurrent().User;
        if (currentUser is null) return;

        security.AddAccessRule(new FileSystemAccessRule(
            currentUser,
            FileSystemRights.FullControl,
            InheritanceFlags.None,
            PropagationFlags.None,
            AccessControlType.Allow));

        info.SetAccessControl(security);
    }
}
