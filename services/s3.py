import boto3
from urllib.parse import urlparse
from botocore.exceptions import ClientError


class S3:
    def __init__(self):
        self.bucket_name =  "video-867344466664-ap-southeast-2-an"

        self.s3 = boto3.client("s3")

    def upload_file(self, local_path, s3_key, content_type=None):
        """
        上传本地文件到 S3

        :param local_path: 本地文件路径
        :param s3_key: S3 object key，例如 folder/test.txt
        :param content_type: 文件类型，例如 image/png
        :return: True/False
        """
        try:
            extra_args = {}

            if content_type:
                extra_args["ContentType"] = content_type

            self.s3.upload_file(
                local_path,
                self.bucket_name,
                s3_key,
                ExtraArgs=extra_args if extra_args else None
            )

            print(f"文件上传S3成功: {s3_key}")
            return f"s3://{self.bucket_name}/{s3_key}"

        except ClientError as e:
            print(f"文件上传S3失败: {e}")
            return None
        
    def download_file(self, s3_path, local_path):
        """
    从 s3://bucket/key 格式下载文件

    :param s3_path: s3 URI
                     例如 s3://bucket/videos/test.mp4
    :param local_path: 本地保存路径
    :return: True/False
    """
        try:
            parsed = urlparse(s3_path)

            bucket_name = parsed.netloc
            s3_key = parsed.path.lstrip("/")

            self.s3.download_file(
                bucket_name,
                s3_key,
                local_path
            )

            print(f"文件下载成功: {local_path}")

        except ClientError as e:
            print(f"文件下载S3失败: {e}")

