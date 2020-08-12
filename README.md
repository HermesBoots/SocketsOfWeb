# SocketsOfWeb, a Thread-Safe WebSocket Implementation

## The Story

As more applications developed in software are starting to be made on the web, the WebSocket protocol is becoming much more popular in order to overcome some of the limitations of HTTP. Discord, a popular chat room program, uses it, and a few years ago I was interested in writing a bot to handle certain tasks on the service. Many libraries already existed for this, but since this was a personal project, I didn't want to skip over learning about the underlying logic of the protocol so I decided to implement it myself in Python.

I started trying to learn WebSocket by downloading existing, open-source implementations and looking at their code, but most of them used Python's new asynchronous programming features. I had to learn those to understand the code, but my goal was to learn WebSocket, not that. I thus decided to switch to reading the original protocol specification myself, and testing my implementation against a public echo server (it waits for you to send it a message then sends it back).

Since existing solutions all seemed to be asynchronous, I decided to make mine concurrent instead. This accomplishes essentially the same thing, especially because of Python's limited support for using multiple CPU threads at a time, but is more difficult to design for correctly.

I wrote this during a calm period whlie working another software job. Sometimes I just get the itch to develop a project from scratch, even if it's something that's already been done before.

<img alt="Parallel lines on a road" src="https://i.imgur.com/wVmYSbc.png" width=100>

## Author

Sam Hermes [GitHub](https://github.com/HermesBoots/) [LinkedIn](https://www.linkedin.com/in/samuel-hermes/) [Twitter](https://twitter.com/SamHermesBoots)
