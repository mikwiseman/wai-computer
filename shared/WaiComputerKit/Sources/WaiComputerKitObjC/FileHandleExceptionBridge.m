#import "WaiComputerKitObjC.h"

static NSString *const WAIFileHandleExceptionDomain = @"is.waiwai.WaiComputerKit.FileHandleException";

static void WAISetExceptionError(NSException *exception, NSError **error) {
    if (error == NULL) {
        return;
    }
    NSDictionary *userInfo = @{
        NSLocalizedDescriptionKey: exception.reason ?: exception.name,
        @"exceptionName": exception.name
    };
    *error = [NSError errorWithDomain:WAIFileHandleExceptionDomain code:1 userInfo:userInfo];
}

BOOL WAIFileHandleGetOffset(NSFileHandle *handle, unsigned long long *offset, NSError **error) {
    @try {
        if (offset != NULL) {
            *offset = [handle offsetInFile];
        }
        return YES;
    } @catch (NSException *exception) {
        WAISetExceptionError(exception, error);
        return NO;
    }
}

BOOL WAIFileHandleSeekToOffset(NSFileHandle *handle, unsigned long long offset, NSError **error) {
    @try {
        [handle seekToFileOffset:offset];
        return YES;
    } @catch (NSException *exception) {
        WAISetExceptionError(exception, error);
        return NO;
    }
}

BOOL WAIFileHandleWriteData(NSFileHandle *handle, NSData *data, NSError **error) {
    @try {
        [handle writeData:data];
        return YES;
    } @catch (NSException *exception) {
        WAISetExceptionError(exception, error);
        return NO;
    }
}

BOOL WAIFileHandleSynchronize(NSFileHandle *handle, NSError **error) {
    @try {
        [handle synchronizeFile];
        return YES;
    } @catch (NSException *exception) {
        WAISetExceptionError(exception, error);
        return NO;
    }
}

BOOL WAIFileHandleClose(NSFileHandle *handle, NSError **error) {
    @try {
        [handle closeFile];
        return YES;
    } @catch (NSException *exception) {
        WAISetExceptionError(exception, error);
        return NO;
    }
}
