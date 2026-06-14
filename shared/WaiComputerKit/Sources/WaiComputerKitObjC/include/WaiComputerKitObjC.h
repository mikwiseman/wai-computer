#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

BOOL WAIFileHandleGetOffset(NSFileHandle *handle, unsigned long long *offset, NSError **error);
BOOL WAIFileHandleSeekToOffset(NSFileHandle *handle, unsigned long long offset, NSError **error);
BOOL WAIFileHandleWriteData(NSFileHandle *handle, NSData *data, NSError **error);
BOOL WAIFileHandleSynchronize(NSFileHandle *handle, NSError **error);
BOOL WAIFileHandleClose(NSFileHandle *handle, NSError **error);

NS_ASSUME_NONNULL_END
